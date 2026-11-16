"""Stage 3/5 (A04, S02): Pulse real-time WebSocket STT.

usage: python scripts/asr_stream.py clips/EN01.wav en [--finalize-at 0.5] [--no-pace] [--tag NAME]
Sends raw PCM16 (no WAV header) in 100 ms frames at real-time pace, then close_stream.
The final transcript is built only from is_final=true segments; the run waits for is_last=true.
"""
import argparse
import asyncio
import json
import pathlib
import urllib.parse

import websockets

from common import ROOT, WSS, Clock, auth, log, pcm_from_wav, sha256


async def stream(path, language, *, model='pulse', finalize_at=None, pace=True, tag='A04', extra=None,
                 frame_ms=100, wait_last_s=20, sample_rate_override=None):
    pcm, rate = pcm_from_wav(path)
    query = {'model': model, 'language': language, 'encoding': 'linear16',
             'sample_rate': str(sample_rate_override or rate), **(extra or {})}
    url = f'{WSS}/stt/live?' + urllib.parse.urlencode(query)
    frame = int(rate * 2 * frame_ms / 1000)
    events, result = [], dict(test=tag, clip=pathlib.Path(path).stem, url=url, model=model, params=query,
                              input_sha256=sha256(pcm), audio_duration_s=round(len(pcm) / (rate * 2), 3))
    clock = Clock()
    try:
        ws = await websockets.connect(url, additional_headers=auth(), open_timeout=20, max_size=None)
    except Exception as error:  # handshake rejections are evidence, not crashes
        response = getattr(error, 'response', None)
        result.update(handshake_error=repr(error)[:300], handshake_status=getattr(response, 'status_code', None),
                      handshake_body=(response.body or b'')[:500].decode('utf-8', 'replace') if response else None)
        return log('asr_stream', result)
    result['handshake_ms'] = clock.ms()
    marks = {}

    async def reader():
        try:
            async for message in ws:
                at = clock.ms()
                data = json.loads(message) if isinstance(message, str) else {'_binary': len(message)}
                events.append({'t_ms': at, **data})
                if data.get('type') == 'transcription':
                    marks.setdefault('first_response_ms', at)
                    if data.get('transcription') or data.get('transcript'):
                        marks.setdefault('first_text_ms', at)
                    if data.get('from_finalize'):
                        marks.setdefault('finalize_response_ms', at)
                if data.get('is_last'):
                    marks['is_last_ms'] = at
                    return
        except websockets.ConnectionClosed:
            pass

    task = asyncio.create_task(reader())
    sent, finalize_sent = 0, False
    send_start = clock.ms()
    for offset in range(0, len(pcm), frame):
        await ws.send(pcm[offset:offset + frame])
        sent += 1
        if finalize_at is not None and not finalize_sent and offset / len(pcm) >= finalize_at:
            await ws.send(json.dumps({'type': 'finalize'}))
            marks['finalize_sent_ms'], finalize_sent = clock.ms(), True
        if pace:
            target = send_start + (sent * frame_ms)
            await asyncio.sleep(max(0, (target - clock.ms()) / 1000))
    marks['last_audio_sent_ms'] = clock.ms()
    await ws.send(json.dumps({'type': 'close_stream'}))
    marks['close_stream_sent_ms'] = clock.ms()
    try:
        await asyncio.wait_for(task, wait_last_s)
    except asyncio.TimeoutError:
        result['timeout_waiting_is_last'] = True
        task.cancel()
    try:
        await asyncio.wait_for(ws.wait_closed(), 5)
        result['server_closed_after_is_last'] = True
    except asyncio.TimeoutError:
        result['server_closed_after_is_last'] = False
        await ws.close()
    result.update(close_code=ws.close_code, close_reason=ws.close_reason)

    finals = [e for e in events if e.get('type') == 'transcription' and e.get('is_final')]
    partials = [e for e in events if e.get('type') == 'transcription' and not e.get('is_final')]
    transcript = ' '.join((e.get('transcription') or e.get('transcript') or '').strip() for e in finals).strip()
    result.update(marks, frames_sent=sent, frame_ms=frame_ms, paced=pace, transcript=transcript,
                  n_events=len(events), n_partials=len(partials), n_finals=len(finals),
                  n_is_last=sum(1 for e in events if e.get('is_last')),
                  n_from_finalize=sum(1 for e in events if e.get('from_finalize')),
                  is_last_without_is_final=any(e.get('is_last') and not e.get('is_final') for e in events),
                  errors=[e for e in events if e.get('type') == 'error' or e.get('status') == 'error'],
                  session_ids=sorted({e['session_id'] for e in events if e.get('session_id')}),
                  final_languages=sorted({str(e.get('language')) for e in finals}),
                  final_after_last_audio_ms=round(marks['is_last_ms'] - marks['last_audio_sent_ms'], 1) if 'is_last_ms' in marks else None,
                  events=events)
    return log('asr_stream', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('clip')
    parser.add_argument('language')
    parser.add_argument('--model', default='pulse')
    parser.add_argument('--finalize-at', type=float)
    parser.add_argument('--no-pace', action='store_true')
    parser.add_argument('--tag', default='A04')
    args = parser.parse_args()
    out = asyncio.run(stream(ROOT / args.clip, args.language, model=args.model, finalize_at=args.finalize_at,
                             pace=not args.no_pace, tag=args.tag))
    print(json.dumps({k: v for k, v in out.items() if k != 'events'}, ensure_ascii=False, indent=1))
    for event in out.get('events', []):
        print(json.dumps(event, ensure_ascii=False)[:260])
