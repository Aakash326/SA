"""Stage 9 repeat: Kannada '23 November' with voice spoorthi (judge flagged 'pattu mooru'). 3 fresh syntheses + a
control on basava, each judged blind-first by Gemini. Also one run with the date written in words."""
import json
import time

import requests

from common import HTTP, RESULTS, Clock, auth, headers_of, log, sha256, wav_info
from ext_tts import TARGETS, TEXT
from judge import tts_blind, tts_judge

out = RESULTS / 'ext_tts_repeat'
out.mkdir(exist_ok=True)
text = TEXT['kn'][2]
variants = [('spoorthi', text, f'r{i}') for i in (1, 2, 3)] + [('basava', text, 'r1'),
            ('spoorthi', 'ನಿಮ್ಮ ಸಭೆ ನವೆಂಬರ್ ಇಪ್ಪತ್ತ ಮೂರರಂದು ಬೆಳಿಗ್ಗೆ 9:05 ಕ್ಕೆ ಇದೆ.', 'words')]
for voice, t, tag in variants:
    payload = {'text': t, 'voice_id': voice, 'model': 'lightning_v3.1_pro', 'language': 'kn', 'sample_rate': 24000, 'output_format': 'wav'}
    clock = Clock()
    r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json'}, json=payload, timeout=60)
    path = out / f'kn-datetime-{voice}-{tag}.wav'
    path.write_bytes(r.content)
    case = f'R-kn-datetime-{voice}-{tag}'
    blind = tts_blind(case, path, 'kn')['reply']
    verdict = tts_judge(case, path, 'kn', t, TARGETS['datetime'], blind.get('heard', ''))['reply']
    log('probe_kn_date', dict(test='P-KN-DATE', voice=voice, tag=tag, request=payload, status=r.status_code, elapsed_ms=clock.ms(),
                              headers=headers_of(r), wav=wav_info(r.content), output_sha256=sha256(r.content), output=str(path.relative_to(RESULTS.parent)),
                              heard=blind.get('heard'), targets=verdict.get('targets')))
    print(voice, tag, '|', blind.get('heard'), '|', [(x['id'], x['result']) for x in verdict.get('targets', [])])
    time.sleep(0.5)
