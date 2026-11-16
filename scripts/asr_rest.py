"""Stage 3 (A01-A03): Pulse pre-recorded STT over the clip manifest.

usage: python scripts/asr_rest.py templates/clips.csv pulse [--language-override multi-indic] [--cohort telugu] [--run NAME]
One request per clip, sequential, paced under the documented 25 requests/minute.
"""
import argparse
import csv
import json
import time

import requests

from common import HTTP, ROOT, Clock, auth, body_excerpt, headers_of, log, sha256

parser = argparse.ArgumentParser()
parser.add_argument('manifest')
parser.add_argument('model')
parser.add_argument('--language-override')
parser.add_argument('--cohort')
parser.add_argument('--run', default='asr_rest')
parser.add_argument('--pace', type=float, default=2.6)
args = parser.parse_args()

rows = list(csv.DictReader(open(ROOT / args.manifest, encoding='utf-8-sig')))
if args.cohort:
    rows = [r for r in rows if r['cohort'] in args.cohort.split(',')]

for row in rows:
    audio = (ROOT / row['path']).read_bytes()
    language = args.language_override or row['api_language']
    params = {'model': args.model, 'language': language}
    clock = Clock()
    try:
        r = requests.post(f'{HTTP}/stt/', params=params,
                          headers={**auth(), 'Content-Type': 'application/octet-stream'}, data=audio, timeout=120)
        elapsed = clock.ms()
        try:
            body = r.json()
        except ValueError:
            body = {'_raw': body_excerpt(r)}
        entry = dict(status=r.status_code, headers=headers_of(r), body=body,
                     transcript=body.get('transcription') if isinstance(body, dict) else None)
    except requests.RequestException as error:
        elapsed = clock.ms()
        entry = dict(status=None, error=repr(error), transcript=None)
    out = log(args.run, dict(test='A01', clip_id=row['clip_id'], cohort=row['cohort'], model=args.model,
                             params=params, url=f'{HTTP}/stt/', input_sha256=sha256(audio),
                             audio_duration_s=float(row['duration_s']), elapsed_ms=elapsed, **entry))
    print(row['clip_id'], language, out['status'], elapsed, 'ms |', json.dumps(out.get('transcript') if out.get('transcript') is not None else out.get('body') or out.get('error'), ensure_ascii=False)[:160])
    time.sleep(args.pace)
