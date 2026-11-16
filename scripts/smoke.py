"""Stage 1: one Lightning TTS REST request and one Pulse STT REST request."""
import json
import sys

import requests

from common import HTTP, RESULTS, Clock, auth, body_excerpt, headers_of, log, sha256, wav_info

out = RESULTS / 'smoke'
out.mkdir(parents=True, exist_ok=True)

payload = {'text': 'Hello from the QA test.', 'voice_id': 'meher', 'model': 'lightning_v3.1_pro',
           'sample_rate': 24000, 'output_format': 'wav'}
clock = Clock()
r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json', 'Accept': 'audio/wav'},
                  json=payload, timeout=60)
elapsed = clock.ms()
info = wav_info(r.content) if r.ok else None
if r.ok:
    (out / 'hello.wav').write_bytes(r.content)
row = log('smoke', dict(test='SMOKE-TTS', url=f'{HTTP}/tts', request=payload, status=r.status_code,
                        elapsed_ms=elapsed, headers=headers_of(r), wav=info,
                        output_sha256=sha256(r.content) if r.ok else None,
                        body=None if info else body_excerpt(r)))
print('TTS', r.status_code, elapsed, 'ms', info)
print(json.dumps(row['headers'], indent=1))

clip = sys.argv[1] if len(sys.argv) > 1 else str(out / 'hello.wav')
for model in ('pulse', 'pulse-pro'):
    audio = open(clip, 'rb').read()
    clock = Clock()
    r = requests.post(f'{HTTP}/stt/', params={'model': model, 'language': 'en'},
                      headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=audio, timeout=120)
    elapsed = clock.ms()
    row = log('smoke', dict(test=f'SMOKE-STT-{model}', url=r.url, status=r.status_code, elapsed_ms=elapsed,
                            headers=headers_of(r), input_sha256=sha256(audio), body=body_excerpt(r, 2000)))
    print('STT', model, r.status_code, elapsed, 'ms', r.text[:500])
    print(json.dumps(row['headers'], indent=1))
