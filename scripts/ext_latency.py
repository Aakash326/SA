"""Stage 9 X-LAT: controlled TTS latency/RTF study (Gnani report-4 protocol), run with no other traffic.

Three English texts (~60 / ~400 / ~930 chars), voice kaitlyn, lightning_v3.1_pro, 24 kHz PCM16.
Per transport and length: 2 warm-ups (excluded) + 5 measured trials, sequential, order randomised per block (seed 4104).
Transports:
  rest      POST /tts, dispatch -> full body; RTF = elapsed / decoded audio seconds
  sse       POST /tts/live, TTFA = dispatch -> first decoded audio event; total = -> done:true
  ws_cold   new socket per request; TTFA from request send, plus handshake reported separately
  ws_warm   one open socket reused for consecutive requests (reuse verified in S03); TTFA from request send
Also records, for WebSocket, time of last audio chunk (the 'complete' tail is studied in Stage 7, not here).
"""
import asyncio
import base64
import json
import random
import statistics
import time

import requests
import websockets

from common import HTTP, RESULTS, WSS, Clock, auth, log, percentile, wav_info
from tts_ws import ws_run

TEXTS = {
    'short': 'Your appointment is confirmed for Monday at 9:05 AM. Thank you.',
    'medium': ('Thank you for calling customer support. Your current balance is 2,450 rupees, and your last payment was '
               'received on 23 November. Your next statement will be generated at the end of this month. If you would like '
               'to set up automatic payments, please visit the payments section of the app, choose your bank account, and '
               'confirm the mandate with the one-time password we send you. Is there anything else I can help you with today?'),
    'long': ('Welcome to the quarterly account review. Over the last three months, your portfolio received four deposits, '
             'totalling 18,250 rupees, and two withdrawals of 3,000 rupees each. The largest single transaction was a transfer '
             'of 7,500 rupees on 14 October. Your systematic investment plan continued without interruption, and every '
             'instalment was debited on the fifth of the month as scheduled. Please note that from 1 December, the minimum '
             'balance requirement for your account type will change to 5,000 rupees. If your balance falls below this level, '
             'a small monthly charge may apply. You can avoid this charge by keeping a fixed deposit linked to the account. '
             'We have also updated our security practices. We will never ask for your password, your PIN, or your one-time '
             'password over the phone. If anyone contacts you claiming to be from the bank and asks for these details, '
             'please end the call and report it through the app. Finally, your annual tax statement is now available for '
             'download. Thank you for banking with us, and have a pleasant day.'),
}
BASE = {'voice_id': 'kaitlyn', 'model': 'lightning_v3.1_pro', 'language': 'en', 'sample_rate': 24000}
WARMUP, TRIALS = 2, 5


def rest(text):
    clock = Clock()
    r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json'},
                      json={**BASE, 'text': text, 'output_format': 'wav'}, timeout=120)
    total = clock.ms()
    info = wav_info(r.content) if r.ok else None
    return dict(status=r.status_code, total_ms=total, audio_s=info and info['duration_s'],
                request_id=r.headers.get('x-request-id'))


def sse(text):
    clock = Clock()
    r = requests.post(f'{HTTP}/tts/live', json={**BASE, 'text': text}, stream=True, timeout=120,
                      headers={**auth(), 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
    first, nbytes, done = None, 0, None
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith('data:'):
            data = json.loads(line[5:].strip())
            if data.get('audio'):
                nbytes += len(base64.b64decode(data['audio']))
                first = first or clock.ms()
            if data.get('done'):
                done = clock.ms()
                break
    return dict(status=r.status_code, ttfa_ms=first, total_ms=done, audio_s=round(nbytes / 2 / 24000, 3),
                request_id=r.headers.get('x-request-id'))


async def ws_cold(text):
    row = await ws_run(text, tag='X-LAT-ws_cold', after_complete_s=0.2)
    audio = [f['t_ms'] for f in row.get('frames', []) if f.get('audio_bytes')]
    return dict(ttfa_ms=row.get('first_audio_ms'), handshake_ms=row.get('handshake_ms'), last_audio_ms=audio[-1] if audio else None,
                total_ms=row.get('complete_ms'), audio_s=row.get('audio_s'), request_id=(row.get('request_ids') or [None])[0])


async def ws_warm_series(text, n):
    out = []
    async with websockets.connect(f'{WSS}/tts/live', additional_headers=auth(), max_size=None) as conn:
        for _ in range(n):
            clock = Clock()
            await conn.send(json.dumps({**BASE, 'text': text, 'output_format': 'pcm'}))
            first, last, nbytes, rid = None, None, 0, None
            while True:
                data = json.loads(await asyncio.wait_for(conn.recv(), 60))
                rid = rid or data.get('request_id')
                if data.get('status') == 'chunk':
                    nbytes += len(base64.b64decode(data['data']['audio']))
                    first = first or clock.ms()
                    last = clock.ms()
                if data.get('status') in ('complete', 'error'):
                    break
            out.append(dict(ttfa_ms=first, last_audio_ms=last, total_ms=clock.ms(), audio_s=round(nbytes / 2 / 24000, 3), request_id=rid))
    return out


def main():
    rng = random.Random(4104)
    rows = []
    for length in ('short', 'medium', 'long'):
        text = TEXTS[length]
        for transport in rng.sample(['rest', 'sse', 'ws_cold', 'ws_warm'], 4):
            if transport == 'ws_warm':
                results = asyncio.run(ws_warm_series(text, WARMUP + TRIALS))
            else:
                results = []
                for _ in range(WARMUP + TRIALS):
                    results.append(rest(text) if transport == 'rest' else sse(text) if transport == 'sse' else asyncio.run(ws_cold(text)))
                    time.sleep(0.5)
            for i, res in enumerate(results):
                res.update(length=length, chars=len(text), transport=transport, trial=i + 1, warmup=i < WARMUP,
                           rtf=round(res['total_ms'] / 1000 / res['audio_s'], 3) if res.get('total_ms') and res.get('audio_s') else None,
                           rtf_last_audio=round(res['last_audio_ms'] / 1000 / res['audio_s'], 3) if res.get('last_audio_ms') and res.get('audio_s') else None)
                log('ext_latency', dict(test='X-LAT', **res))
                rows.append(res)
            measured = [r for r in results if not r['warmup']]
            print(length, transport, 'TTFA', [r.get('ttfa_ms') for r in measured], 'total', [r['total_ms'] for r in measured])
    summary = {}
    for length in TEXTS:
        for transport in ('rest', 'sse', 'ws_cold', 'ws_warm'):
            m = [r for r in rows if r['length'] == length and r['transport'] == transport and not r['warmup']]
            pick = lambda k: [r[k] for r in m if r.get(k) is not None]
            summary[f'{length}/{transport}'] = dict(
                n=len(m), chars=len(TEXTS[length]), audio_s_median=statistics.median(pick('audio_s')),
                ttfa_median_ms=statistics.median(pick('ttfa_ms')) if pick('ttfa_ms') else None,
                ttfa_max_ms=max(pick('ttfa_ms')) if pick('ttfa_ms') else None,
                total_median_ms=statistics.median(pick('total_ms')), rtf_median=statistics.median(pick('rtf')),
                rtf_to_last_audio_median=statistics.median(pick('rtf_last_audio')) if pick('rtf_last_audio') else None,
                handshake_median_ms=statistics.median(pick('handshake_ms')) if pick('handshake_ms') else None)
    (RESULTS / 'ext_latency_summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    for k, v in summary.items():
        print(f'{k:16}', json.dumps(v))


if __name__ == '__main__':
    main()
