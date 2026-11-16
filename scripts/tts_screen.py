"""Stage 4: automated provisional screen of synthesized audio, and the synthetic round-trip cohort.

usage: python scripts/tts_screen.py templates/tts_prompts.csv tts
       python scripts/tts_screen.py templates/challenge_prompts.csv challenge --stream

Each WAV is transcribed by Pulse (and Pulse Pro for English); every target regex is applied to
each transcript. A target is `auto_pass` only when every available recogniser agrees; a
disagreement is `auto_review`. None of this is a human listening verdict.
"""
import argparse
import asyncio
import csv
import json
import re
import time

import requests

from asr_stream import stream
from common import HTTP, RESULTS, ROOT, Clock, auth, headers_of, log, sha256

parser = argparse.ArgumentParser()
parser.add_argument('manifest')
parser.add_argument('folder')
parser.add_argument('--stream', action='store_true', help='also run the Pulse WebSocket on each file')
parser.add_argument('--rescore', action='store_true', help='re-apply target rules to the saved CSV; no API calls')
args = parser.parse_args()


def transcribe(path, model, language, case_id):
    audio = path.read_bytes()
    clock = Clock()
    r = requests.post(f'{HTTP}/stt/', params={'model': model, 'language': language},
                      headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=audio, timeout=120)
    body = r.json() if 'json' in r.headers.get('content-type', '') else {}
    log(f'screen_{args.folder}', dict(test='T01-SCREEN', case_id=case_id, model=model, params={'model': model, 'language': language},
                                      status=r.status_code, elapsed_ms=clock.ms(), headers=headers_of(r),
                                      input_sha256=sha256(audio), body=body))
    time.sleep(2.6)
    return body.get('transcription', '') if r.ok else f'<HTTP {r.status_code}>'


previous = {}
if args.rescore:  # re-apply target rules to transcripts already logged; no API calls
    for old in csv.DictReader(open(RESULTS / f'screen_{args.folder}.csv', encoding='utf-8-sig')):
        previous[old['case_id']] = {k[6:]: v for k, v in old.items() if k.startswith('heard_') and v != ''}
        previous.setdefault('_human', {})[(old['case_id'], old['target_id'])] = (old['human_verdict'], old['human_heard'], old['human_notes'])

rows = []
for row in csv.DictReader(open(ROOT / args.manifest, encoding='utf-8-sig')):
    path = RESULTS / args.folder / f"{row['case_id']}.wav"
    if args.rescore:
        heard = previous[row['case_id']]
    else:
        heard = {'pulse': transcribe(path, 'pulse', row['language'], row['case_id'])}
        if row['language'] == 'en':
            heard['pulse-pro'] = transcribe(path, 'pulse-pro', 'en', row['case_id'])
        if args.stream:
            out = asyncio.run(stream(path, row['language'], tag='ROUNDTRIP-WS'))
            heard['pulse-ws'] = out.get('transcript', '<no transcript>')
    for target in json.loads(row['targets_json']):
        hits = {name: bool(re.search(target['accept'], text.lower())) for name, text in heard.items()}
        verdict = 'auto_pass' if all(hits.values()) else ('auto_fail' if not any(hits.values()) else 'auto_review')
        rows.append(dict(case_id=row['case_id'], category=row['category'], text=row['text'], voice_id=row['voice_id'],
                         language=row['language'], paired_with=row['paired_with'], target_id=target['id'],
                         written=target['written'], must_hear=target['must_hear'], critical=target['critical'],
                         automated_provisional=verdict, **{f'hit_{k}': v for k, v in hits.items()},
                         **{f'heard_{k}': v for k, v in heard.items()},
                         **dict(zip(('human_verdict', 'human_heard', 'human_notes'),
                                    previous.get('_human', {}).get((row['case_id'], target['id']), ('', '', ''))))))
    print(row['case_id'], '|', row['text'])
    for name, text in heard.items():
        print(f'    {name:10}', text)
    print('    ', [(r['target_id'], r['automated_provisional']) for r in rows if r['case_id'] == row['case_id']])

fields = []
for r in rows:
    fields += [k for k in r if k not in fields]
with open(RESULTS / f'screen_{args.folder}.csv', 'w', newline='', encoding='utf-8-sig') as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, restval='')
    writer.writeheader()
    writer.writerows(rows)
counts = {}
for r in rows:
    counts[r['automated_provisional']] = counts.get(r['automated_provisional'], 0) + 1
print('targets', len(rows), counts)
