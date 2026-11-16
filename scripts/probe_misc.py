"""Stage 7 repeats: zero-audio close_stream, and word duplication at a finalize boundary."""
import asyncio
import json

import websockets

from asr_stream import stream
from common import ROOT, WSS, Clock, auth, log


async def zero_audio(language):
    url = f'{WSS}/stt/live?model=pulse&language={language}&encoding=linear16&sample_rate=16000'
    async with websockets.connect(url, additional_headers=auth()) as conn:
        clock = Clock()
        await conn.send(json.dumps({'type': 'close_stream'}))
        msgs = []
        try:
            async for m in conn:
                msgs.append(json.loads(m))
                if msgs[-1].get('is_last'):
                    break
        except websockets.ConnectionClosed:
            pass
    final = ' '.join(m.get('transcription', '') for m in msgs if m.get('is_final')).strip()
    log('probe_misc', dict(test='P-ZERO-AUDIO', language=language, transcript=final, messages=msgs, elapsed_ms=clock.ms()))
    print('zero-audio', language, repr(final), [m.get('duration') for m in msgs], [m.get('session_id') for m in msgs][:1])


async def main():
    for language in ('en', 'en', 'en', 'hi', 'hi'):
        await zero_audio(language)
        await asyncio.sleep(1)
    for clip, lang in (('CS03', 'hi'), ('CS03', 'hi'), ('CS03', 'hi'), ('EN03', 'en'), ('HI06', 'hi'), ('CS05', 'hi')):
        base = await stream(ROOT / 'clips' / f'{clip}.wav', lang, tag='P-FINALIZE-control')
        fin = await stream(ROOT / 'clips' / f'{clip}.wav', lang, finalize_at=0.5, tag='P-FINALIZE')
        segments = [e.get('transcription') for e in fin['events'] if e.get('is_final')]
        log('probe_misc', dict(test='P-FINALIZE-pair', clip=clip, control=base['transcript'], finalize=fin['transcript'],
                               segments=segments, sessions=fin['session_ids']))
        print(f'{clip} control : {base["transcript"]}\n{clip} finalize: {fin["transcript"]}\n          segments: {segments}')


asyncio.run(main())
