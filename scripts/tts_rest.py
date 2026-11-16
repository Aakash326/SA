"""Stage 4 (T01/T02): Lightning REST synthesis for every row of a prompt CSV, sequentially.

usage: python scripts/tts_rest.py templates/tts_prompts.csv [--out tts] [--run tts_rest]
"""
import argparse
import csv
import time

import requests

from common import HTTP, RESULTS, ROOT, Clock, auth, body_excerpt, headers_of, log, sha256, wav_info

parser = argparse.ArgumentParser()
parser.add_argument('manifest')
parser.add_argument('--out', default='tts')
parser.add_argument('--run', default='tts_rest')
args = parser.parse_args()
out = RESULTS / args.out
out.mkdir(parents=True, exist_ok=True)

for row in csv.DictReader(open(ROOT / args.manifest, encoding='utf-8-sig')):
    payload = {'text': row['text'], 'voice_id': row['voice_id'], 'model': row['model'], 'language': row['language'],
               'sample_rate': int(row['sample_rate']), 'output_format': 'wav'}
    clock = Clock()
    r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json'}, json=payload, timeout=90)
    elapsed = clock.ms()
    info = wav_info(r.content) if r.ok else None
    if info:
        (out / f"{row['case_id']}.wav").write_bytes(r.content)
    log(args.run, dict(test='T01', case_id=row['case_id'], category=row['category'], url=f'{HTTP}/tts', request=payload,
                       status=r.status_code, elapsed_ms=elapsed, headers=headers_of(r), wav=info,
                       output=f"results/{args.out}/{row['case_id']}.wav" if info else None,
                       output_sha256=sha256(r.content) if info else None, body=None if info else body_excerpt(r)))
    print(row['case_id'], r.status_code, elapsed, 'ms', info or body_excerpt(r)[:200])
    time.sleep(0.5)
