"""Stage 9 review fix P1-2: paired condition deltas — each derived clip against its own parent's clean result.

Parent results come from the core REST run (templates/clips.csv) or from the extension REST run. Pairs whose parent
has no clean Pulse result are excluded and counted. Output: results/ext_asr_paired.json.
"""
import csv
import json

from common import RESULTS, ROOT, read_jsonl
from metrics import corpus, score

canon = list(csv.DictReader(open(RESULTS / 'ext_asr_manifest_canonical.csv', encoding='utf-8-sig')))
refs = {c['clip_id']: c['reference'] for c in csv.DictReader(open(ROOT / 'templates' / 'ext_clips.csv', encoding='utf-8-sig'))}
core = {r['source_clip_id']: r for r in csv.DictReader(open(ROOT / 'templates' / 'clips.csv', encoding='utf-8-sig'))}
hyp = {r['clip_id']: r.get('transcript') or '' for r in read_jsonl('ext_asr_rest') if r.get('status') == 200}
core_hyp = {r['clip_id']: r.get('transcript') or '' for r in read_jsonl('asr_rest') if r.get('status') == 200}
gnani = {r['clip_id']: r for r in csv.DictReader(open(ROOT.parent / 'gnani' / 'data' / 'asr_manifest.csv', encoding='utf-8-sig'))}

out, missing = {}, []
for c in canon:
    if c['is_derived'] != 'true':
        continue
    parent, chain = c['parent_utterance_id'], [c['parent_utterance_id']]
    while parent in gnani and gnani[parent].get('source_id') and gnani[parent]['source_id'] != parent:
        parent = gnani[parent]['source_id']  # walk 8 kHz -> clean so every pair is measured against the clean root
        chain.append(parent)
    if parent in core:
        p_hyp, p_ref = core_hyp.get(core[parent]['clip_id']), core[parent]['reference']
    elif parent in hyp:
        p_hyp, p_ref = hyp[parent], refs[parent]
    else:
        missing.append((c['clip_id'], parent))
        continue
    ref = refs[c['clip_id']]
    out.setdefault(c['condition'], []).append(dict(clip=c['clip_id'], parent=parent, chain=chain, clean=score(ref, p_hyp), variant=score(ref, hyp[c['clip_id']]),
                                                   clean_text=p_hyp, variant_text=hyp[c['clip_id']]))
summary = {}
for cond, pairs in sorted(out.items()):
    a, b = corpus([p['clean'] for p in pairs]), corpus([p['variant'] for p in pairs])
    summary[cond] = dict(pairs=len(pairs), reference_words=a['reference_words'], clean_parent_wer=round(a['wer'], 4),
                         variant_wer=round(b['wer'], 4), delta_pp=round((b['wer'] - a['wer']) * 100, 1),
                         worse=sum(1 for p in pairs if p['variant']['word_edits'] > p['clean']['word_edits']),
                         same=sum(1 for p in pairs if p['variant']['word_edits'] == p['clean']['word_edits']),
                         better=sum(1 for p in pairs if p['variant']['word_edits'] < p['clean']['word_edits']))
summary['excluded_no_parent_result'] = missing
(RESULTS / 'ext_asr_paired.json').write_text(json.dumps(dict(summary=summary, pairs=out), ensure_ascii=False, indent=1), encoding='utf-8')
for k, v in summary.items():
    print(k, v)
