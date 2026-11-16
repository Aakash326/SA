"""Stage 7 extension: paired REST vs WebSocket on human numeric clips (labelled as an extension cohort).

Clips come from the licensed Google SVQ selection already in ../gnani; none overlap templates/clips.csv.
"""
import asyncio
import csv
import json
import re
import shutil
import time

import requests

from asr_stream import stream
from common import HTTP, ROOT, auth, log, sha256

GNANI = ROOT.parent / 'gnani'
used = {r['source_clip_id'] for r in csv.DictReader(open(ROOT / 'templates' / 'clips.csv', encoding='utf-8-sig'))}
rows = [r for r in csv.DictReader(open(GNANI / 'data' / 'asr_manifest.csv', encoding='utf-8-sig'))
        if r['language'] == 'en-IN' and r['category'] in ('numbers', 'clean_en') and re.search(r'\d', r['reference_transcript'])
        and r['clip_id'] not in used and not r['derivation_json']]
(ROOT / 'clips' / 'ext').mkdir(parents=True, exist_ok=True)
out_rows = []
for r in rows:
    target = ROOT / 'clips' / 'ext' / f"{r['clip_id']}.wav"
    shutil.copyfile(GNANI / r['input_path'], target)
    numbers = re.findall(r'\d+', r['reference_transcript'])
    rest = requests.post(f'{HTTP}/stt/', params={'model': 'pulse', 'language': 'en'},
                         headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=target.read_bytes(), timeout=60)
    rest_text = rest.json().get('transcription', '') if rest.ok else f'<HTTP {rest.status_code}>'
    ws = asyncio.run(stream(target, 'en', tag='EXT-NUM-WS'))
    ws_text = ws.get('transcript', '')
    row = dict(test='EXT-NUM', clip_id=r['clip_id'], speaker_id=r['speaker_id'], reference=r['reference_transcript'],
               reference_origin=r['reference_origin'], numbers=numbers, input_sha256=sha256(target),
               rest=rest_text, ws=ws_text, rest_status=rest.status_code,
               rest_numbers_ok=all(n in re.sub(r'(?<=\d),(?=\d)', '', rest_text) for n in numbers),
               ws_numbers_ok=all(n in re.sub(r'(?<=\d),(?=\d)', '', ws_text) for n in numbers))
    log('numeric_extension', row)
    out_rows.append(row)
    print(f"{r['clip_id']:14} ref={r['reference_transcript'][:55]:55} | REST={rest_text[:55]:55} | WS={ws_text[:55]}")
    time.sleep(2.6)
print(json.dumps(dict(clips=len(out_rows), rest_digits_exact=sum(r['rest_numbers_ok'] for r in out_rows),
                      ws_digits_exact=sum(r['ws_numbers_ok'] for r in out_rows))))
