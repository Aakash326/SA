"""Stage 9 review fix P0-2/P0-3: focused confirmation of the TTS WebSocket completion gap and its impact.

Five sequential short syntheses per mode, kaitlyn / lightning_v3.1_pro / 24 kHz PCM:
  A  one socket; next request only after `complete`; a {"type":"ping"} is sent 500 ms after the last audio chunk to
     show that the socket and this client answer within one round trip while `complete` is still pending.
  B  one socket; next request sent as soon as the previous request's audio has gone quiet for 400 ms (before its
     `complete`). Records whether the server accepts, rejects or queues it, by request_id.
  C  a fresh connection per request, waiting for `complete` (comparison for A).
Timestamps: time.perf_counter() taken immediately after websockets returns each frame (monotonic), plus IST wall clock.
Frame traces without audio payloads are saved to results/evidence/completion_traces/.
Never more than one synthesis is started by this client before the previous one has delivered all its audio.
"""
import asyncio
import json
import time

import websockets

from common import IST, RESULTS, WSS, auth, log

TEXTS = ['Your reference ID is 0070.', 'Your appointment is confirmed for Monday.', 'Please do not share your OTP.',
         'Your balance is 2,450 rupees.', 'Thank you for calling.']
BASE = {'voice_id': 'kaitlyn', 'model': 'lightning_v3.1_pro', 'language': 'en', 'sample_rate': 24000, 'output_format': 'pcm'}
OUT = RESULTS / 'evidence' / 'completion_traces'
QUIET_MS = 400


def wall():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).astimezone(IST).strftime('%H:%M:%S.%f')[:-3]


class Recorder:
    def __init__(self, conn, t0):
        self.conn, self.t0, self.frames = conn, t0, []

    def ms(self):
        return round((time.perf_counter() - self.t0) * 1000, 1)

    async def reader(self):
        try:
            async for message in self.conn:
                at = self.ms()
                d = json.loads(message)
                audio = (d.get('data') or {}).get('audio') if isinstance(d.get('data'), dict) else None
                self.frames.append(dict(t_ms=at, wall_ist=wall(), status=d.get('status'), type=d.get('type'),
                                        request_id=d.get('request_id'), audio_b64_len=len(audio) if audio else 0,
                                        message=d.get('message'), errors=d.get('errors')))
        except websockets.ConnectionClosed as closed:
            self.frames.append(dict(t_ms=self.ms(), wall_ist=wall(), closed=closed.rcvd.code if closed.rcvd else None))

    def event(self, label, **kw):
        self.frames.append(dict(t_ms=self.ms(), wall_ist=wall(), client_event=label, **kw))


async def wait_for(rec, pred, timeout=20.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if any(pred(f) for f in rec.frames):
            return True
        await asyncio.sleep(0.005)
    return False


async def wait_quiet(rec, since_index):
    """Return once audio has started after `since_index` and no chunk has arrived for QUIET_MS."""
    while True:
        chunks = [f for f in rec.frames[since_index:] if f.get('status') == 'chunk']
        if chunks and rec.ms() - chunks[-1]['t_ms'] >= QUIET_MS:
            return chunks[-1]['t_ms']
        await asyncio.sleep(0.01)


def per_request(frames):
    """Group server frames by request_id and compute first audio / last audio / complete."""
    out, sends = {}, [f for f in frames if f.get('client_event') == 'send']
    for f in frames:
        rid = f.get('request_id')
        if not rid:
            continue
        r = out.setdefault(rid, dict(request_id=rid, chunks=0))
        if f['status'] == 'chunk':
            r['chunks'] += 1
            r.setdefault('first_ms', f['t_ms'])
            r['last_ms'] = f['t_ms']
        elif f['status'] == 'complete':
            r['complete_ms'] = f['t_ms']
        elif f['status'] == 'error':
            r['error'] = f.get('message')
    rows = sorted(out.values(), key=lambda r: r.get('first_ms', r.get('complete_ms', 1e12)))
    for i, r in enumerate(rows):
        if i < len(sends):
            r['sent_ms'] = sends[i]['t_ms']
            r['ttfa_ms'] = round(r['first_ms'] - r['sent_ms'], 1) if 'first_ms' in r else None
        if 'complete_ms' in r and 'last_ms' in r:
            r['gap_ms'] = round(r['complete_ms'] - r['last_ms'], 1)
    return rows


async def mode_a():
    t0 = time.perf_counter()
    async with websockets.connect(f'{WSS}/tts/live', additional_headers=auth(), max_size=None) as conn:
        rec = Recorder(conn, t0)
        task = asyncio.create_task(rec.reader())
        pings = []
        for text in TEXTS:
            n = len(rec.frames)
            rec.event('send', text=text)
            await conn.send(json.dumps({**BASE, 'text': text}))
            last = await wait_quiet(rec, n)
            await asyncio.sleep(max(0, (last + 500 - rec.ms()) / 1000))
            rec.event('ping')
            ping_at = rec.ms()
            await conn.send(json.dumps({'type': 'ping'}))
            got = await wait_for(rec, lambda f: f.get('type') == 'pong' and f['t_ms'] > ping_at, 5)
            pong = next((f['t_ms'] for f in rec.frames if f.get('type') == 'pong' and f['t_ms'] > ping_at), None)
            await wait_for(rec, lambda f: f.get('status') in ('complete', 'error') and f['t_ms'] > ping_at, 20)
            comp = next((f['t_ms'] for f in rec.frames if f.get('status') == 'complete' and f['t_ms'] > ping_at), None)
            pings.append(dict(ping_after_last_audio_ms=round(ping_at - last, 1), pong_rtt_ms=round(pong - ping_at, 1) if got else None,
                              complete_after_pong_ms=round(comp - pong, 1) if got and comp else None))
        await conn.close()
        await task
    return rec.frames, dict(pings=pings)


async def mode_b():
    t0 = time.perf_counter()
    async with websockets.connect(f'{WSS}/tts/live', additional_headers=auth(), max_size=None) as conn:
        rec = Recorder(conn, t0)
        task = asyncio.create_task(rec.reader())
        for text in TEXTS:
            n = len(rec.frames)
            rec.event('send', text=text)
            await conn.send(json.dumps({**BASE, 'text': text}))
            await wait_quiet(rec, n)  # next request goes out before this one's `complete`
        await wait_for(rec, lambda f: f.get('status') in ('complete', 'error'), 1)
        await asyncio.sleep(6)  # let outstanding `complete` frames arrive
        await conn.close()
        await task
    return rec.frames, {}


async def mode_c():
    frames = []
    for text in TEXTS:
        t0 = time.perf_counter()
        async with websockets.connect(f'{WSS}/tts/live', additional_headers=auth(), max_size=None) as conn:
            rec = Recorder(conn, t0)
            rec.event('connected')
            task = asyncio.create_task(rec.reader())
            rec.event('send', text=text)
            await conn.send(json.dumps({**BASE, 'text': text}))
            await wait_for(rec, lambda f: f.get('status') in ('complete', 'error'), 20)
            await asyncio.sleep(0.3)
            await conn.close()
            await task
            frames.append(rec.frames)
    return frames, {}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, fn in (('A_same_socket_wait_complete', mode_a), ('B_same_socket_send_after_last_audio', mode_b),
                     ('C_fresh_connection', mode_c)):
        frames, extra = await fn()
        groups = frames if name.startswith('C') else [frames]
        reqs = [r for g in groups for r in per_request(g)]
        closes = [f['closed'] for g in groups for f in g if 'closed' in f]
        errors = [f for g in groups for f in g if f.get('status') == 'error' or f.get('type') == 'error']
        results[name] = dict(requests=reqs, close_codes=closes, error_frames=errors, **extra)
        (OUT / f'{name}.json').write_text(json.dumps(dict(mode=name, frames=groups), indent=1), encoding='utf-8')
        log('probe_completion', dict(test='P-COMPLETION', mode=name, requests=reqs, close_codes=closes, error_frames=errors, **extra))
        print(f'== {name}')
        for r in reqs:
            print('  ', {k: r.get(k) for k in ('request_id', 'sent_ms', 'ttfa_ms', 'first_ms', 'last_ms', 'complete_ms', 'gap_ms', 'chunks', 'error')})
        if extra:
            print('  ', extra)
        print('   close codes', closes, 'errors', errors)
        await asyncio.sleep(2)
    (RESULTS / 'probe_completion_summary.json').write_text(json.dumps(results, indent=1), encoding='utf-8')


asyncio.run(main())
