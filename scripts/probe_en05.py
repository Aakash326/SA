"""Stage 7: repeat the EN05 REST-vs-WebSocket year discrepancy under varied client settings."""
import asyncio
import time

import requests

from asr_stream import stream
from common import HTTP, ROOT, auth, log, sha256

clip = ROOT / 'clips' / 'EN05.wav'
audio = clip.read_bytes()
for i in range(3):
    r = requests.post(f'{HTTP}/stt/', params={'model': 'pulse', 'language': 'en'},
                      headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=audio, timeout=60)
    log('probe_en05', dict(test='P-EN05-REST', run=i + 1, status=r.status_code, input_sha256=sha256(audio),
                           transcript=r.json().get('transcription')))
    print('REST', i + 1, r.json().get('transcription'))
    time.sleep(2.6)

variants = [
    ('128ms-4096B paced (documented chunk)', dict(frame_ms=128)),
    ('20ms paced', dict(frame_ms=20)),
    ('100ms unpaced (burst)', dict(frame_ms=100, pace=False)),
    ('100ms paced itn_normalize=true', dict(frame_ms=100, extra={'itn_normalize': 'true'})),
    ('100ms paced language=multi-eu', dict(frame_ms=100, language='multi-eu')),
]
for name, kw in variants:
    language = kw.pop('language', 'en')
    out = asyncio.run(stream(clip, language, tag=f'P-EN05-WS {name}', **kw))
    print(f'WS  {name:40}', out.get('transcript'), '| partials:', [e.get('transcript') for e in out['events'] if not e.get('is_final')][-1:])
