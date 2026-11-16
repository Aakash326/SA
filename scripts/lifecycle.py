"""Stage 5/6 (S02, S03, R01, R02): stream lifecycle, keepalive, cancellation and one controlled overlap.

usage: python scripts/lifecycle.py [--only S02,S03-STT,S03-TTS,R01,R02]
Results go to results/lifecycle.jsonl and results/concurrency.jsonl.
"""
import argparse
import asyncio
import json
import threading
import time
import urllib.parse

import requests
import websockets

from asr_stream import stream
from common import HTTP, ROOT, WSS, Clock, auth, body_excerpt, headers_of, log, pcm_from_wav, wav_info
from tts_ws import LONG, SHORT, brief, ws_run

TTS_REQ = {'voice_id': 'kaitlyn', 'model': 'lightning_v3.1_pro', 'language': 'en', 'sample_rate': 24000}


def stt_url(**query):
    return f'{WSS}/stt/live?' + urllib.parse.urlencode({'model': 'pulse', 'language': 'en', 'encoding': 'linear16',
                                                         'sample_rate': '16000', **query})


async def collect(conn, clock, until_s, stop=None):
    """Read messages until timeout, close, or stop(msg) is true."""
    got = []
    try:
        while True:
            message = await asyncio.wait_for(conn.recv(), until_s)
            data = json.loads(message) if isinstance(message, str) else {'_binary': len(message)}
            got.append(dict(t_ms=clock.ms(), **({k: v for k, v in data.items() if k != 'data'} if isinstance(data, dict) else {'raw': data})))
            if stop and stop(data):
                break
    except asyncio.TimeoutError:
        got.append(dict(t_ms=clock.ms(), _timeout_s=until_s))
    except websockets.ConnectionClosed as closed:
        got.append(dict(t_ms=clock.ms(), _closed=closed.code, _reason=closed.reason))
    return got


# ---------------------------------------------------------------- S02: finalize vs close_stream
async def s02():
    for clip in ('CS03', 'TE03'):
        out = await stream(ROOT / 'clips' / f'{clip}.wav', 'hi' if clip.startswith('CS') else 'te', finalize_at=0.5, tag='S02-finalize')
        finals = [e for e in out['events'] if e.get('is_final')]
        after = [e for e in finals if e['t_ms'] > out.get('finalize_response_ms', 1e9)]
        summary = dict(test='S02', clip=clip, finalize_sent_ms=out.get('finalize_sent_ms'),
                       finalize_response_ms=out.get('finalize_response_ms'), n_from_finalize=out['n_from_finalize'],
                       n_is_last=out['n_is_last'], finals_after_finalize=len(after), transcript=out['transcript'],
                       is_last_on_finalize=any(e.get('is_last') and e.get('from_finalize') for e in out['events']),
                       close_code=out.get('close_code'), session_ids=out['session_ids'])
        log('lifecycle', summary)
        print('S02', json.dumps(summary, ensure_ascii=False))


# ---------------------------------------------------------------- S03: STT keepalive / timeout
async def s03_stt():
    clock = Clock()
    conn = await websockets.connect(stt_url(), additional_headers=auth())
    pongs = []
    for _ in range(3):
        await conn.send(json.dumps({'type': 'ping'}))
        pongs += await collect(conn, clock, 3, stop=lambda d: d.get('type') == 'pong')
        await asyncio.sleep(2)
    pcm, _ = pcm_from_wav(ROOT / 'clips' / 'EN02.wav')
    for i in range(0, len(pcm), 3200):
        await conn.send(pcm[i:i + 3200])
        await asyncio.sleep(0.1)
    await conn.send(json.dumps({'type': 'close_stream'}))
    tail = await collect(conn, clock, 15, stop=lambda d: d.get('is_last'))
    finals = ' '.join(e.get('transcription', '') for e in tail if e.get('is_final')).strip()
    row = dict(test='S03-STT-ping', pings=3, pongs=sum(1 for e in pongs if e.get('type') == 'pong'), ping_events=pongs,
               transcript_after_pings=finals, is_last=any(e.get('is_last') for e in tail), close=conn.close_code)
    log('lifecycle', row)
    print('S03 stt ping', json.dumps({k: row[k] for k in ('pongs', 'transcript_after_pings', 'is_last', 'close')}))
    await conn.close()

    # Documented ?timeout=N (seconds) inactivity close on the keep-alive page.
    for seconds in (5,):
        clock = Clock()
        conn = await websockets.connect(stt_url(timeout=str(seconds)), additional_headers=auth())
        events = await collect(conn, clock, seconds + 30)
        row = dict(test='S03-STT-timeout', timeout_param_s=seconds, events=events, close=dict(code=conn.close_code, reason=conn.close_reason),
                   closed_at_ms=events[-1]['t_ms'] if events else None)
        log('lifecycle', row)
        print('S03 stt timeout', json.dumps(row, ensure_ascii=False)[:400])
        await conn.close()


# ---------------------------------------------------------------- S03: TTS socket lifecycle (mostly undocumented)
async def s03_tts():
    # Normal completion: does the server close after `complete`, as the streaming page says?
    for i in range(2):
        print('S03 tts complete', brief(await ws_run(SHORT, tag='S03-TTS-complete', after_complete_s=10)))

    # Second request on the same socket after `complete`.
    clock = Clock()
    conn = await websockets.connect(f'{WSS}/tts/live', additional_headers=auth())
    await conn.send(json.dumps({**TTS_REQ, 'text': SHORT, 'output_format': 'pcm'}))
    first = await collect(conn, clock, 20, stop=lambda d: d.get('status') in ('complete', 'error'))
    second = []
    try:
        await conn.send(json.dumps({**TTS_REQ, 'text': 'Second request on the same socket.', 'output_format': 'pcm'}))
        second = await collect(conn, clock, 20, stop=lambda d: d.get('status') in ('complete', 'error'))
    except websockets.ConnectionClosed as closed:
        second = [dict(_send_failed_closed=closed.code)]
    row = dict(test='S03-TTS-reuse', first_statuses=[e.get('status') for e in first][-3:],
               second=[{k: v for k, v in e.items()} for e in second if e.get('status') != 'chunk'][:6],
               second_chunks=sum(1 for e in second if e.get('status') == 'chunk'), close=conn.close_code)
    log('lifecycle', row)
    print('S03 tts reuse', json.dumps(row, ensure_ascii=False)[:500])
    await conn.close()

    # Keepalive probe: TTS ping is not documented. Observation only.
    clock = Clock()
    conn = await websockets.connect(f'{WSS}/tts/live', additional_headers=auth())
    await conn.send(json.dumps({'type': 'ping'}))
    events = await collect(conn, clock, 5)
    row = dict(test='S03-TTS-ping-probe', events=events, close=conn.close_code)
    log('lifecycle', row)
    print('S03 tts ping', json.dumps(row, ensure_ascii=False)[:400])
    await conn.close()

    # Idle sockets: plain, and with the guide's ?timeout=5 (not in TTS docs). Observe up to 75 s.
    for query in ('timeout=5', ''):
        clock = Clock()
        conn = await websockets.connect(f'{WSS}/tts/live' + (f'?{query}' if query else ''), additional_headers=auth())
        events = await collect(conn, clock, 75)
        row = dict(test='S03-TTS-idle', query=query or None, events=events, close=dict(code=conn.close_code, reason=conn.close_reason),
                   open_after_75s=any('_timeout_s' in e for e in events))
        log('lifecycle', row)
        print('S03 tts idle', query or '(none)', json.dumps(row, ensure_ascii=False)[:400])
        await conn.close()


# ---------------------------------------------------------------- R02: client cancel then fresh request
async def r02():
    for i in range(2):
        clock = Clock()
        conn = await websockets.connect(f'{WSS}/tts/live', additional_headers=auth())
        await conn.send(json.dumps({**TTS_REQ, 'text': LONG, 'output_format': 'pcm'}))
        first = await collect(conn, clock, 20, stop=lambda d: d.get('status') == 'chunk')
        await conn.close()
        closed_ms = clock.ms()
        # Immediately start a new request: is the cancelled synthesis still holding the single slot?
        rows = []
        for attempt in range(1, 4):
            out = await ws_run(SHORT, tag='R02-after-cancel')
            rows.append(dict(attempt=attempt, at_ms=clock.ms(), ok=out.get('status_sequence_ok'), errors=out.get('errors'),
                             first_audio_ms=out.get('first_audio_ms'), close=out.get('close')))
            if out.get('status_sequence_ok'):
                break
            await asyncio.sleep(1.0)
        row = dict(test='R02', run=i + 1, cancelled_after_first_chunk_ms=first[-1]['t_ms'] if first else None,
                   client_close_ms=closed_ms, follow_up=rows)
        log('lifecycle', row)
        print('R02', json.dumps(row, ensure_ascii=False)[:500])
        await asyncio.sleep(3)


# ---------------------------------------------------------------- R01: one controlled overlap
def rest_tts(text, label, sink, start):
    clock = Clock()
    r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json'},
                      json={**TTS_REQ, 'text': text, 'output_format': 'wav'}, timeout=120)
    sink[label] = dict(start_offset_ms=round((clock.start - start) * 1000, 1), status=r.status_code, elapsed_ms=clock.ms(),
                       headers=headers_of(r), audio=wav_info(r.content) if r.ok else None,
                       body=None if r.ok else body_excerpt(r))


def rest_stt(label, sink, start):
    clock = Clock()
    r = requests.post(f'{HTTP}/stt/', params={'model': 'pulse', 'language': 'en'},
                      headers={**auth(), 'Content-Type': 'application/octet-stream'},
                      data=(ROOT / 'clips' / 'EN01.wav').read_bytes(), timeout=120)
    sink[label] = dict(start_offset_ms=round((clock.start - start) * 1000, 1), status=r.status_code,
                       elapsed_ms=clock.ms(), headers=headers_of(r), body=body_excerpt(r, 400))


def r01(repeats=3):
    for run in range(1, repeats + 1):
        for variant in ('tts+tts', 'tts+stt'):
            sink, start = {}, time.perf_counter()
            first = threading.Thread(target=rest_tts, args=(LONG, 'active', sink, start))
            first.start()
            time.sleep(0.4)  # active synthesis is in flight (single long request takes > 1 s)
            if variant == 'tts+tts':
                rest_tts(SHORT, 'overlap', sink, start)
            else:
                rest_stt('overlap', sink, start)
            first.join()
            retry = None
            if sink['overlap']['status'] != 200:
                if variant == 'tts+tts':
                    rest_tts(SHORT, 'retry', sink, start)
                else:
                    rest_stt('retry', sink, start)
                retry = sink['retry']
            overlap_ended = sink['overlap']['start_offset_ms'] + sink['overlap']['elapsed_ms']
            active_ended = sink['active']['start_offset_ms'] + sink['active']['elapsed_ms']
            row = dict(test='R01', run=run, variant=variant, active=sink['active'], overlap=sink['overlap'], retry=retry,
                       overlap_finished_before_active=overlap_ended < active_ended,
                       retry_inclusive_ms=round(retry['start_offset_ms'] + retry['elapsed_ms'] - sink['overlap']['start_offset_ms'], 1) if retry else None)
            log('concurrency', row)
            print('R01', run, variant, 'active', sink['active']['status'], sink['active']['elapsed_ms'],
                  '| overlap', sink['overlap']['status'], sink['overlap']['elapsed_ms'], sink['overlap'].get('body'),
                  '| retry', retry and retry['status'])
            time.sleep(3)


async def main(only):
    if not only or 'S02' in only:
        await s02()
    if not only or 'S03-STT' in only:
        await s03_stt()
    if not only or 'S03-TTS' in only:
        await s03_tts()
    if not only or 'R02' in only:
        await r02()
    if not only or 'R01' in only:
        r01()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--only')
    args = parser.parse_args()
    asyncio.run(main(set(args.only.split(',')) if args.only else None))
