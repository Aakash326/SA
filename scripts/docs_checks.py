"""Stage 6 (D02-D05): settle documented contradictions with one or two requests each."""
import json

import requests

from common import HTTP, RESULTS, Clock, auth, body_excerpt, headers_of, log, sha256, wav_info


def call(test, method, path, note, **kwargs):
    clock = Clock()
    r = requests.request(method, f'{HTTP}{path}', headers={**auth(), **kwargs.pop('headers', {})}, timeout=60, **kwargs)
    row = dict(test=test, note=note, method=method, url=f'{HTTP}{path}', request=kwargs.get('json'),
               status=r.status_code, elapsed_ms=clock.ms(), headers=headers_of(r))
    return r, row


# D04: both documented voices endpoint paths.
catalog = {}
for path in ('/lightning-v3.1-pro/get_voices', '/lightning-v3.1/get_voices'):
    r, row = call('D04', 'GET', path, 'voices endpoint path')
    voices = r.json().get('voices', []) if r.ok else []
    catalog[path] = voices
    row.update(voice_count=len(voices), body=None if r.ok else body_excerpt(r))
    log('docs_checks', row)
    print('D04', path, r.status_code, len(voices))
(RESULTS / 'voices.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding='utf-8')
for path, voices in catalog.items():
    ids = {v.get('voiceId') for v in voices}
    meher = next((v for v in voices if v.get('voiceId') == 'meher'), None)
    print('  ', path, 'meher:', json.dumps(meher, ensure_ascii=False)[:300] if meher else None,
          '| kaitlyn' , 'kaitlyn' in ids, '| sophie', 'sophie' in ids)

# D02: model omitted -> which model serves the request? D03: Accept vs output_format default.
base = {'text': 'This is a default check.', 'voice_id': 'meher', 'sample_rate': 24000}
cases = [
    ('D03', 'output_format omitted, Accept audio/wav', {**base, 'model': 'lightning_v3.1_pro'}, {'Accept': 'audio/wav'}),
    ('D03', 'output_format omitted, no Accept', {**base, 'model': 'lightning_v3.1_pro'}, {}),
    ('D02', 'model omitted, Pro-only voice meher, wav', {**base, 'output_format': 'wav'}, {}),
    ('D05', 'sample_rate omitted (documented default 44100), wav',
     {'text': 'This is a default check.', 'voice_id': 'meher', 'model': 'lightning_v3.1_pro', 'output_format': 'wav'}, {}),
]
for test, note, payload, headers in cases:
    r, row = call(test, 'POST', '/tts', note, json=payload, headers={'Content-Type': 'application/json', **headers})
    info = wav_info(r.content) if r.ok else None
    row.update(wav=info, body_bytes=len(r.content), body_head_hex=r.content[:12].hex() if r.ok else None,
               output_sha256=sha256(r.content) if r.ok else None, body=None if r.ok else body_excerpt(r))
    log('docs_checks', row)
    print(test, note, '->', r.status_code, row['headers'].get('content-type'), len(r.content), 'bytes', info or body_excerpt(r)[:200])
