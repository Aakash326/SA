"""Stage 5 (S01): Lightning TTS over WebSocket and SSE with per-frame monotonic timing.

usage: python scripts/tts_ws.py 'Your reference ID is 0070.' kaitlyn en          # one WS run
       python scripts/tts_ws.py --repeat 5                                       # S01 repeatability study
       python scripts/tts_ws.py --sse 3                                          # SSE parity

Clocks (all client side, monotonic):
  handshake_ms      connect start -> socket open (includes DNS/TCP/TLS)
  first_audio_ms    request sent -> first decoded audio chunk
  complete_ms       request sent -> status=complete
  gaps              arrival delta between consecutive audio chunks
  underrun          simulated playout: playback starts once `buffer_ms` of audio is buffered and
                    stalls whenever the next chunk has not arrived when the buffer drains
"""
import argparse
import asyncio
import base64
import json
import time

import requests
import websockets

from common import HTTP, RESULTS, WSS, Clock, auth, headers_of, log, percentile, sha256, wrap_wav

SHORT = 'Your reference ID is 0070.'
LONG = ('Thank you for calling. Your current balance is minus 1,499 rupees. Your last payment of 2,350 rupees '
        'was received on 23 November 2026 at 9:05 AM. Please do not share your OTP with anyone. To speak to an '
        'agent, stay on the line; otherwise, you can complete your KYC from the app before the end of the month.')


def playout(chunks, rate, buffer_ms=200):
    """chunks: [(arrival_ms, samples)]. Returns stall count and total stall time."""
    if not chunks:
        return dict(underruns=0, stall_ms=0.0, start_ms=None)
    buffered, start = 0.0, None
    for at, samples in chunks:
        buffered += samples / rate * 1000
        if buffered >= buffer_ms:
            start = at
            break
    if start is None:
        start = chunks[-1][0]
    clock_ms, stalls, stall_ms, play_head = start, 0, 0.0, start
    for at, samples in chunks:
        if at > play_head:
            if at > start:
                stalls += 1
                stall_ms += at - play_head
            play_head = at
        play_head += samples / rate * 1000
    return dict(underruns=stalls, stall_ms=round(stall_ms, 1), start_ms=round(start, 1), buffer_ms=buffer_ms)


async def ws_run(text, voice='kaitlyn', language='en', *, model='lightning_v3.1_pro', rate=24000, tag='S01',
                 query='', extra=None, save_as=None, wait_s=60, after_complete_s=3.0):
    url = f'{WSS}/tts/live' + (f'?{query}' if query else '')
    request = {'text': text, 'voice_id': voice, 'model': model, 'language': language, 'sample_rate': rate,
               'output_format': 'pcm', **(extra or {})}
    result = dict(test=tag, url=url, request=request)
    clock = Clock()
    try:
        ws = await websockets.connect(url, additional_headers=auth(), open_timeout=20, max_size=None)
    except Exception as error:
        response = getattr(error, 'response', None)
        result.update(handshake_error=repr(error)[:300], handshake_status=getattr(response, 'status_code', None))
        return log('tts_ws', result)
    result['handshake_ms'] = clock.ms()
    await ws.send(json.dumps(request))
    sent = clock.ms()
    frames, chunks, pcm = [], [], bytearray()
    try:
        while True:
            message = await asyncio.wait_for(ws.recv(), wait_s)
            at = clock.ms() - sent
            data = json.loads(message) if isinstance(message, str) else {'_binary': len(message)}
            audio = (data.get('data') or {}).get('audio') if isinstance(data.get('data'), dict) else None
            frame = {k: v for k, v in data.items() if k != 'data'}
            frame['t_ms'] = round(at, 1)
            if audio:
                raw = base64.b64decode(audio)
                pcm += raw
                chunks.append((at, len(raw) // 2))
                frame['audio_bytes'] = len(raw)
            elif data.get('data') is not None:
                frame['data'] = data['data']
            frames.append(frame)
            if data.get('status') in ('complete', 'error') or data.get('type') == 'error':
                break
    except asyncio.TimeoutError:
        result['timeout_waiting'] = wait_s
    except websockets.ConnectionClosed as closed:
        result['closed_before_complete'] = dict(code=closed.code, reason=closed.reason)
    # Docs: after `complete` the server closes the socket. Observe whether it does.
    try:
        await asyncio.wait_for(ws.wait_closed(), after_complete_s)
        result['server_closed_within_s'] = after_complete_s
    except asyncio.TimeoutError:
        result['server_closed_within_s'] = None
        await ws.close()
    result['close'] = dict(code=ws.close_code, reason=ws.close_reason)

    arrivals = [c[0] for c in chunks]
    gaps = [round(b - a, 1) for a, b in zip(arrivals, arrivals[1:])]
    statuses = [f.get('status') for f in frames]
    complete = next((f for f in frames if f.get('status') == 'complete'), None)
    audio_s = len(pcm) / 2 / rate
    if save_as and pcm:
        (RESULTS / 'tts_ws').mkdir(exist_ok=True)
        (RESULTS / 'tts_ws' / f'{save_as}.wav').write_bytes(wrap_wav(bytes(pcm), rate))
    result.update(
        first_audio_ms=round(arrivals[0], 1) if arrivals else None,
        complete_ms=complete['t_ms'] if complete else None,
        chunk_count=len(chunks), audio_s=round(audio_s, 3), pcm_sha256=sha256(bytes(pcm)) if pcm else None,
        gap_max_ms=max(gaps) if gaps else None, gap_p50_ms=percentile(gaps, 0.5), gap_p95_ms=percentile(gaps, 0.95),
        realtime_factor=round(complete['t_ms'] / 1000 / audio_s, 3) if complete and audio_s else None,
        statuses=sorted(set(map(str, statuses))), status_sequence_ok=bool(frames) and statuses[-1] == 'complete'
        and all(s == 'chunk' for s in statuses[:-1] if s != 'word_timestamp'),
        audio_after_complete=any(f.get('audio_bytes') for f in frames[frames.index(complete) + 1:]) if complete else None,
        request_ids=sorted({f['request_id'] for f in frames if f.get('request_id')}),
        session_ids=sorted({f['session_id'] for f in frames if f.get('session_id')}),
        errors=[f for f in frames if f.get('status') == 'error' or f.get('type') == 'error'],
        playout_200=playout(chunks, rate, 200), playout_0=playout(chunks, rate, 1),
        output=f'results/tts_ws/{save_as}.wav' if save_as and pcm else None, frames=frames)
    return log('tts_ws', result)


def sse_run(text, voice='kaitlyn', language='en', *, model='lightning_v3.1_pro', rate=24000, tag='S01-SSE'):
    payload = {'text': text, 'voice_id': voice, 'model': model, 'language': language, 'sample_rate': rate}
    clock = Clock()
    r = requests.post(f'{HTTP}/tts/live', json=payload, stream=True, timeout=60,
                      headers={**auth(), 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
    headers_ms = clock.ms()
    events, pcm, first = [], bytearray(), None
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        at = clock.ms()
        if line.startswith('data:'):
            try:
                data = json.loads(line[5:].strip())
            except ValueError:
                events.append(dict(t_ms=at, unparsed=line[:200]))
                continue
            if data.get('audio'):
                raw = base64.b64decode(data['audio'])
                pcm += raw
                first = first or at
            events.append(dict(t_ms=at, **{k: v for k, v in data.items() if k != 'audio'},
                               audio_bytes=len(base64.b64decode(data['audio'])) if data.get('audio') else 0))
            if data.get('done'):
                break
        else:
            events.append(dict(t_ms=at, line=line[:120]))
    return log('tts_ws', dict(test=tag, url=f'{HTTP}/tts/live', request=payload, status=r.status_code,
                              headers=headers_of(r), headers_ms=headers_ms, first_audio_ms=first,
                              complete_ms=events[-1]['t_ms'] if events else None,
                              done_seen=any(e.get('done') for e in events), audio_s=round(len(pcm) / 2 / rate, 3),
                              chunk_count=sum(1 for e in events if e.get('audio_bytes')),
                              audio_nested_under_data=False, events=events))


def brief(row):
    keys = ('test', 'handshake_ms', 'first_audio_ms', 'complete_ms', 'chunk_count', 'audio_s', 'gap_max_ms',
            'realtime_factor', 'status_sequence_ok', 'server_closed_within_s', 'close', 'request_ids', 'errors',
            'playout_200', 'closed_before_complete', 'timeout_waiting', 'handshake_error', 'done_seen', 'status')
    return json.dumps({k: row[k] for k in keys if k in row}, ensure_ascii=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('text', nargs='?', default=SHORT)
    parser.add_argument('voice', nargs='?', default='kaitlyn')
    parser.add_argument('language', nargs='?', default='en')
    parser.add_argument('--repeat', type=int)
    parser.add_argument('--sse', type=int)
    args = parser.parse_args()
    if args.repeat:
        for name, text in (('short', SHORT), ('long', LONG)):
            for i in range(1, args.repeat + 1):
                print(name, i, brief(asyncio.run(ws_run(text, tag=f'S01-{name}', save_as=f'{name}_{i}'))))
                time.sleep(1.5)
    elif args.sse:
        for i in range(1, args.sse + 1):
            print('sse', i, brief(sse_run(SHORT)))
            time.sleep(1.5)
    else:
        print(brief(asyncio.run(ws_run(args.text, args.voice, args.language, save_as='single'))))
