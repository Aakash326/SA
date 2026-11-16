"""Stage 7: repeat the Pulse Pro no-speech observation with controls.

Inputs: the three manifest no-speech clips plus two generated digital-silence files (1 s, 10 s) and one
-60 dBFS white-noise file. Each runs 3x on pulse-pro and 1x on pulse (control).
"""
import random
import struct
import time

import requests

from common import HTTP, ROOT, auth, log, sha256, wrap_wav

gen = ROOT / 'clips' / 'generated'
gen.mkdir(parents=True, exist_ok=True)
(gen / 'SIL-1s.wav').write_bytes(wrap_wav(b'\x00\x00' * 16000, 16000))
(gen / 'SIL-10s.wav').write_bytes(wrap_wav(b'\x00\x00' * 160000, 16000))
rng = random.Random(7)
amp = 32768 * 10 ** (-60 / 20) * 1.732  # uniform noise with RMS ~ -60 dBFS
(gen / 'NOISE-60dB-4s.wav').write_bytes(wrap_wav(struct.pack('<64000h', *(int(rng.uniform(-amp, amp)) for _ in range(64000))), 16000))

files = [ROOT / 'clips' / f'NS0{i}.wav' for i in (1, 2, 3)] + sorted(gen.glob('*.wav'))
for path in files:
    audio = path.read_bytes()
    for model, runs in (('pulse-pro', 3), ('pulse', 1)):
        for run in range(1, runs + 1):
            r = requests.post(f'{HTTP}/stt/', params={'model': model, 'language': 'en'},
                              headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=audio, timeout=60)
            body = r.json() if 'json' in r.headers.get('content-type', '') else {}
            log('probe_nospeech', dict(test='P-NOSPEECH', clip=path.stem, model=model, run=run, status=r.status_code,
                                       input_sha256=sha256(audio), transcript=body.get('transcription'),
                                       request_id=body.get('request_id'), body=body))
            print(f'{path.stem:16} {model:9} run {run}: {r.status_code} {body.get("transcription")!r} {body.get("request_id", "")}')
            time.sleep(2.6)
