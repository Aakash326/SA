"""Stage 7: completion-tail probe. Time between last audio chunk and status=complete on the TTS WebSocket,
and whether the account's single synthesis slot is still held during that tail."""
import asyncio
import json
import time

import requests
import websockets

from common import HTTP, WSS, Clock, auth, headers_of, body_excerpt, log
from tts_ws import SHORT, ws_run

BASE = {'voice_id': 'kaitlyn', 'model': 'lightning_v3.1_pro', 'language': 'en', 'sample_rate': 24000}


def tail(row):
    audio = [f['t_ms'] for f in row.get('frames', []) if f.get('audio_bytes')]
    return round(row['complete_ms'] - audio[-1], 1) if audio and row.get('complete_ms') else None


async def variants():
    for name, extra in [('default', {}), ('max_buffer_delay_ms=0', {'max_buffer_delay_ms': 0}),
                        ('max_buffer_delay_ms=500', {'max_buffer_delay_ms': 500}), ('continue=false', {'continue': False}),
                        ('flush=true', {'flush': True})]:
        for i in range(2):
            row = await ws_run(SHORT, tag=f'TAIL {name}', extra=extra, after_complete_s=1)
            log('probe_tail', dict(test='TAIL-variant', variant=name, run=i + 1, tail_ms=tail(row), complete_ms=row.get('complete_ms'),
                                   first_audio_ms=row.get('first_audio_ms'), errors=row.get('errors'), request_ids=row.get('request_ids')))
            print(f'{name:26} run {i + 1}: first_audio {row.get("first_audio_ms")} complete {row.get("complete_ms")} tail {tail(row)} errors {row.get("errors")}')
            time.sleep(1.5)


async def slot_during_tail(probe):
    """Start a WS synthesis; once its last audio chunk has arrived (no chunk for 400 ms) and before `complete`,
    issue ONE second request. Records whether the second request is rejected."""
    clock = Clock()
    conn = await websockets.connect(f'{WSS}/tts/live', additional_headers=auth())
    await conn.send(json.dumps({**BASE, 'text': SHORT, 'output_format': 'pcm'}))
    last_audio, second, complete_at = None, None, None
    while True:
        try:
            message = await asyncio.wait_for(conn.recv(), 0.4)
        except asyncio.TimeoutError:
            if last_audio and second is None:
                at = clock.ms()
                if probe == 'rest':
                    r = await asyncio.to_thread(requests.post, f'{HTTP}/tts', json={**BASE, 'text': 'Second request.', 'output_format': 'wav'},
                                                headers={**auth(), 'Content-Type': 'application/json'}, timeout=60)
                    second = dict(sent_ms=at, status=r.status_code, elapsed_ms=round(clock.ms() - at, 1), headers=headers_of(r),
                                  body=None if r.ok else body_excerpt(r))
                else:
                    row = await ws_run('Second request.', tag='TAIL-slot-second', after_complete_s=1)
                    second = dict(sent_ms=at, ok=row.get('status_sequence_ok'), errors=row.get('errors'),
                                  first_audio_ms=row.get('first_audio_ms'), complete_ms=row.get('complete_ms'), close=row.get('close'))
            continue
        except websockets.ConnectionClosed:
            break
        data = json.loads(message)
        if data.get('status') == 'chunk':
            last_audio = clock.ms()
        if data.get('status') in ('complete', 'error'):
            complete_at = clock.ms()
            break
    await conn.close()
    row = log('probe_tail', dict(test='TAIL-slot', probe=probe, first_last_audio_ms=last_audio, first_complete_ms=complete_at,
                                 second=second, second_sent_before_first_complete=bool(second and complete_at and second['sent_ms'] < complete_at)))
    print('slot', probe, json.dumps({k: row[k] for k in ('first_last_audio_ms', 'first_complete_ms', 'second', 'second_sent_before_first_complete')})[:600])


async def main():
    await variants()
    for probe in ('rest', 'ws', 'rest', 'ws'):
        await slot_during_tail(probe)
        await asyncio.sleep(3)


asyncio.run(main())
