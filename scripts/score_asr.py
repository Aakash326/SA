"""Stage 3: WER/CER, critical slots and no-speech controls for every ASR run.

usage: python scripts/score_asr.py
Reads results/asr_rest*.jsonl and results/asr_stream.jsonl; writes results/asr_scores.csv
and results/asr_summary.json. The last logged attempt per (run, clip) is scored.
"""
import csv
import json

from common import RESULTS, ROOT, read_jsonl
from metrics import corpus, normalize, score

clips = {r['clip_id']: r for r in csv.DictReader(open(ROOT / 'templates' / 'clips.csv', encoding='utf-8-sig'))}


def slots(clip, hypothesis):
    wanted = json.loads(clip['critical_slots'])
    padded = f' {normalize(hypothesis)} '
    hits = [s for s in wanted if f' {normalize(s)} ' in padded]
    return wanted, hits


def score_run(label, transcripts):
    rows = []
    for clip_id, hypothesis in transcripts.items():
        clip = clips[clip_id]
        normalized, raw = score(clip['reference'], hypothesis or ''), score(clip['reference'], hypothesis or '', raw=True)
        wanted, hits = slots(clip, hypothesis or '')
        rows.append(dict(run=label, clip_id=clip_id, cohort=clip['cohort'], reference_status=clip['reference_status'],
                         reference=clip['reference'], hypothesis=hypothesis, **normalized,
                         raw_wer=raw['wer'], raw_cer=raw['cer'], slots_total=len(wanted), slots_correct=len(hits),
                         slots_missed=json.dumps([s for s in wanted if s not in hits], ensure_ascii=False)))
    return rows


def summarise(rows):
    out = {}
    for cohort in sorted({r['cohort'] for r in rows}) + ['all_speech']:
        part = [r for r in rows if (r['cohort'] == cohort or cohort == 'all_speech') and r['cohort'] != 'no_speech']
        if not part:
            continue
        total = corpus(part)
        raw_words = sum(round(r['raw_wer'] * r['ref_word_count']) for r in part)
        out[cohort] = dict(clips=len(part), reference_words=total['reference_words'], word_edits=total['word_edits'],
                           wer=round(total['wer'], 4), cer=round(total['cer'], 4),
                           cer_no_spaces=round(total['cer_no_spaces'], 4),
                           raw_wer=round(raw_words / total['reference_words'], 4),
                           exact_clips=sum(1 for r in part if r['word_edits'] == 0),
                           slots_correct=sum(r['slots_correct'] for r in part), slots_total=sum(r['slots_total'] for r in part))
    silent = [r for r in rows if r['cohort'] == 'no_speech']
    if silent:
        out['no_speech'] = dict(clips=len(silent), false_transcriptions=sum(1 for r in silent if r['false_transcription']),
                                inserted_words=sum(r['no_speech_inserted_words'] for r in silent))
    return out


runs = {}
for name in ('asr_rest', 'asr_rest_pulse_pro'):
    for row in read_jsonl(name):
        if row.get('status') == 200:
            runs.setdefault(f"rest:{row['model']}", {})[row['clip_id']] = row.get('transcript') or ''
for row in read_jsonl('asr_lang_probe'):
    if row.get('status') == 200:
        runs.setdefault(f"rest:{row['model']}:language={row['params']['language']}", {})[row['clip_id']] = row.get('transcript') or ''
for row in read_jsonl('asr_stream'):
    if row.get('test') == 'A04' and 'transcript' in row:
        runs.setdefault(f"ws:{row['model']}", {})[row['clip']] = row['transcript']

all_rows, summary = [], {}
for label, transcripts in runs.items():
    rows = score_run(label, transcripts)
    all_rows += rows
    summary[label] = summarise(rows)

# Paired REST vs WebSocket on the shared clips only.
shared = sorted(set(runs.get('rest:pulse', {})) & set(runs.get('ws:pulse', {})))
if shared:
    summary['paired_rest_vs_ws'] = dict(
        clips=shared,
        rest=summarise(score_run('rest', {c: runs['rest:pulse'][c] for c in shared})).get('all_speech'),
        ws=summarise(score_run('ws', {c: runs['ws:pulse'][c] for c in shared})).get('all_speech'),
        differing=[dict(clip=c, rest=runs['rest:pulse'][c], ws=runs['ws:pulse'][c]) for c in shared
                   if normalize(runs['rest:pulse'][c]) != normalize(runs['ws:pulse'][c])])

with open(RESULTS / 'asr_scores.csv', 'w', newline='', encoding='utf-8-sig') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
    writer.writeheader()
    writer.writerows(all_rows)
(RESULTS / 'asr_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
for label, block in summary.items():
    print('==', label)
    for cohort, numbers in (block.items() if label != 'paired_rest_vs_ws' else block.items()):
        print('  ', cohort, json.dumps(numbers, ensure_ascii=False)[:400])
