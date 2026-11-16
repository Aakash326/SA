"""Stage 7: does number_pronunciation_language=en keep numerals in English for an Indian voice with language=hi?"""
import csv
import time

import requests

from common import HTTP, RESULTS, ROOT, Clock, auth, body_excerpt, headers_of, log, sha256, wav_info

out = RESULTS / 'tts_numlang'
out.mkdir(exist_ok=True)
prompts = {r['case_id']: r for r in csv.DictReader(open(ROOT / 'templates' / 'tts_prompts.csv', encoding='utf-8-sig'))}
for case in ('M2', 'M3', 'I3', 'I4'):
    row = prompts[case]
    payload = {'text': row['text'], 'voice_id': row['voice_id'], 'model': row['model'], 'language': 'hi',
               'number_pronunciation_language': 'en', 'sample_rate': 24000, 'output_format': 'wav'}
    clock = Clock()
    r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json'}, json=payload, timeout=60)
    info = wav_info(r.content) if r.ok else None
    if info:
        (out / f'{case}-numlang-en.wav').write_bytes(r.content)
    heard = ''
    if info:
        time.sleep(1)
        s = requests.post(f'{HTTP}/stt/', params={'model': 'pulse', 'language': 'hi'},
                          headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=r.content, timeout=60)
        heard = s.json().get('transcription', '') if s.ok else f'<HTTP {s.status_code}>'
    log('probe_numlang', dict(test='P-NUMLANG', case_id=case, request=payload, status=r.status_code, elapsed_ms=clock.ms(),
                              headers=headers_of(r), wav=info, output_sha256=sha256(r.content) if info else None,
                              body=None if info else body_excerpt(r), pulse_hi_transcript=heard))
    print(case, r.status_code, '| text:', row['text'], '| heard (pulse, provisional):', heard)
    time.sleep(2.6)
