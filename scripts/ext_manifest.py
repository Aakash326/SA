"""Stage 9 review fix P0-1/P1-2: canonical extension ASR manifest with parent utterances and denominators.

Writes results/ext_asr_manifest_canonical.csv and results/ext_asr_denominators.json.
Columns: clip_id, language, condition, source, parent_utterance_id, is_control, is_derived, included_in_wer,
         reference_words, speaker_id, sha256.
"""
import csv
import json
from collections import Counter, defaultdict

from common import RESULTS, ROOT
from metrics import normalize

gnani = {r['clip_id']: r for r in csv.DictReader(open(ROOT.parent / 'gnani' / 'data' / 'asr_manifest.csv', encoding='utf-8-sig'))}
core = {r['source_clip_id']: r['clip_id'] for r in csv.DictReader(open(ROOT / 'templates' / 'clips.csv', encoding='utf-8-sig'))}
rows = []
for c in csv.DictReader(open(ROOT / 'templates' / 'ext_clips.csv', encoding='utf-8-sig')):
    g = gnani[c['clip_id']]
    derived = c['condition'].startswith(('snr_', 'tel_')) or c['condition'] == 'pause'
    parent = g.get('source_id') or c['clip_id']
    while parent in gnani and gnani[parent].get('source_id') and gnani[parent]['source_id'] != parent:
        parent = gnani[parent]['source_id']  # root clean utterance (8 kHz -> A-law chains resolved)
    words = len(normalize(c['reference']).split()) if c['reference'] else 0
    rows.append(dict(clip_id=c['clip_id'], language=c['language'] or 'none', condition=c['condition'], source=c['source'],
                     parent_utterance_id=parent, parent_in_core_set=core.get(parent, ''), is_control=str(not c['reference']).lower(),
                     is_derived=str(derived).lower(), included_in_wer=str(bool(c['reference'])).lower(), reference_words=words,
                     speaker_id=c['speaker_id'], sha256=c['sha256']))
with open(RESULTS / 'ext_asr_manifest_canonical.csv', 'w', newline='', encoding='utf-8-sig') as h:
    w = csv.DictWriter(h, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

den = {'total_clips': len(rows), 'speech_clips_in_wer': sum(r['included_in_wer'] == 'true' for r in rows),
       'no_speech_controls': sum(r['is_control'] == 'true' for r in rows),
       'derived_clips': sum(r['is_derived'] == 'true' for r in rows),
       'distinct_parent_utterances': len({r['parent_utterance_id'] for r in rows}),
       'distinct_speakers': len({r['speaker_id'] for r in rows if r['speaker_id']}),
       'by_language': {}, 'by_condition': {}}
for key in ('language', 'condition'):
    for v in sorted({r[key] for r in rows}):
        part = [r for r in rows if r[key] == v]
        den[f'by_{key}'][v] = dict(clips=len(part), reference_words=sum(r['reference_words'] for r in part),
                                   derived=sum(r['is_derived'] == 'true' for r in part),
                                   parent_utterances=len({r['parent_utterance_id'] for r in part}),
                                   speakers=len({r['speaker_id'] for r in part if r['speaker_id']}),
                                   parents_shared_with_core_set=sum(1 for r in part if r['parent_in_core_set']))
(RESULTS / 'ext_asr_denominators.json').write_text(json.dumps(den, indent=1), encoding='utf-8')
print(json.dumps({k: v for k, v in den.items() if not k.startswith('by_')}))
for k in ('by_language', 'by_condition'):
    for v, d in den[k].items():
        print(f'{k[3:]:9} {v:11}', d)
