"""Stage 9 X-ASR-4 / X-TTS-2 / X-TTS-3: run the Gemini listening assistant and summarise.

usage: python scripts/ext_judge.py tts        # blind + judge on every extension TTS clip (incl. planted)
       python scripts/ext_judge.py calibrate  # judge on the 20 stage-4 clips a human passed (agreement check)
       python scripts/ext_judge.py asr        # blind transcript on every extension ASR clip, adjudicate differences
       python scripts/ext_judge.py summary    # results/ext_judge_summary.json
Calls run 4 at a time; every reply is cached, so reruns are free.
"""
import csv
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS, ROOT
from judge import MODEL, asr_adjudicate, asr_blind, tts_blind, tts_judge
from metrics import corpus, normalize, score

WORKERS = 4


def pool(fn, items):
    out = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, res in enumerate(ex.map(fn, items), 1):
            out.append(res)
            if i % 10 == 0:
                print(f'  {i}/{len(items)}', flush=True)
    return out


# ------------------------------------------------------------------ TTS
def judge_tts_row(p, audio, targets):
    blind = tts_blind(p['case_id'], audio, p['language'])
    verdict = tts_judge(p['case_id'], audio, p['language'], p['text'], targets, blind['reply'].get('heard', ''))
    return dict(case_id=p['case_id'], language=p['language'], kind=p.get('kind', p.get('category')), voice=p['voice_id'],
                planted=p.get('planted', 'false'), text=p['text'], heard=blind['reply'].get('heard'),
                number_language=blind['reply'].get('number_language'), **verdict['reply'])


def tts():
    rows = list(csv.DictReader(open(ROOT / 'templates' / 'ext_tts_prompts.csv', encoding='utf-8-sig')))
    res = pool(lambda p: judge_tts_row(p, RESULTS / 'ext_tts' / f"{p['case_id']}.wav", json.loads(p['targets_json'])), rows)
    (RESULTS / 'ext_tts_judge.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('tts judged', len(res))


def calibrate():
    """Stage-4 clips with human verdicts (listener R1). Targets converted to the judge format."""
    human = {}
    for r in csv.DictReader(open(RESULTS / 'listening_filled.csv', encoding='utf-8-sig')):
        human.setdefault(r['case_id'], []).append(r)
    items = []
    for name, folder in (('tts_prompts.csv', 'tts'), ('challenge_prompts.csv', 'challenge')):
        for p in csv.DictReader(open(ROOT / 'templates' / name, encoding='utf-8-sig')):
            if p['case_id'] in human:
                targets = [dict(id=t['id'], written=t['written'], must_hear=t['must_hear'] or t['written'], critical=t['critical'])
                           for t in json.loads(p['targets_json'])]
                items.append((p, RESULTS / folder / f"{p['case_id']}.wav", targets))
    res = pool(lambda it: judge_tts_row(it[0], it[1], it[2]), items)
    for r in res:
        marks = {h['target_id']: h['human_verdict'] for h in human[r['case_id']]}
        for t in r.get('targets', []):
            t['human'] = marks.get(t['id'])
    (RESULTS / 'ext_judge_calibration.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('calibration judged', len(res))


# ------------------------------------------------------------------ ASR
def asr():
    clips = {c['clip_id']: c for c in csv.DictReader(open(ROOT / 'templates' / 'ext_clips.csv', encoding='utf-8-sig'))}
    hyps = {}
    for line in open(RESULTS / 'ext_asr_rest.jsonl', encoding='utf-8'):
        r = json.loads(line)
        if r.get('status') == 200:
            hyps[r['clip_id']] = r.get('transcript') or ''

    def one(clip_id):
        c = clips[clip_id]
        blind = asr_blind(clip_id, c['path'], c['language'] or 'none')['reply']
        row = dict(clip_id=clip_id, language=c['language'] or 'none', condition=c['condition'], reference=c['reference'],
                   hypothesis=hyps[clip_id], blind=blind.get('transcript', ''), blind_no_speech=blind.get('no_speech'))
        if c['reference'] and normalize(c['reference']) != normalize(hyps[clip_id]):
            adj = asr_adjudicate(clip_id, c['path'], c['language'], c['reference'], hyps[clip_id], row['blind'])['reply']
            row.update(adjudication=adj)
        return row

    res = pool(one, [c for c in clips if c in hyps])
    (RESULTS / 'ext_asr_judge.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('asr judged', len(res))


# ------------------------------------------------------------------ summary
def summary():
    S = dict(model=MODEL, label='LLM-assessed (Gemini, blind-first); not human MOS, not ground truth')
    tts_rows = json.loads((RESULTS / 'ext_tts_judge.json').read_text(encoding='utf-8'))
    real = [r for r in tts_rows if r['planted'] == 'false']
    planted = [r for r in tts_rows if r['planted'] == 'true']
    S['planted_detection'] = dict(planted=len(planted), caught=sum(1 for r in planted if any(t['result'] == 'wrong' for t in r['targets'])),
                                  rows=[dict(case=r['case_id'], text=r['text'], targets=r['targets']) for r in planted])
    cal = json.loads((RESULTS / 'ext_judge_calibration.json').read_text(encoding='utf-8')) if (RESULTS / 'ext_judge_calibration.json').exists() else []
    pairs = [(t['result'], t.get('human')) for r in cal for t in r.get('targets', []) if t.get('human')]
    S['human_agreement'] = dict(targets=len(pairs), judge_correct_where_human_pass=sum(1 for j, h in pairs if h == 'pass' and j == 'correct'),
                                judge_wrong_where_human_pass=[dict(case=r['case_id'], target=t['id'], heard=t.get('heard'))
                                                              for r in cal for t in r.get('targets', []) if t.get('human') == 'pass' and t['result'] == 'wrong'],
                                judge_ambiguous=sum(1 for j, h in pairs if j == 'ambiguous'))
    langs = sorted({r['language'] for r in real})
    S['tts_by_language'] = {}
    for lang in langs + ['all']:
        part = [r for r in real if lang in ('all', r['language'])]
        ts = [t for r in part for t in r['targets'] if r['kind'] != 'natural']
        S['tts_by_language'][lang] = dict(
            clips=len(part), targets=len(ts), correct=sum(t['result'] == 'correct' for t in ts),
            wrong=sum(t['result'] == 'wrong' for t in ts), ambiguous=sum(t['result'] == 'ambiguous' for t in ts),
            content_complete=sum(1 for r in part if r.get('content_complete')),
            naturalness_mean=round(statistics.mean(r['naturalness_1to5'] for r in part), 2),
            prosody_mean=round(statistics.mean(r['prosody_1to5'] for r in part), 2),
            pronunciation_mean=round(statistics.mean(r['pronunciation_1to5'] for r in part), 2),
            clips_with_artifacts=sum(1 for r in part if r.get('artifacts')))
    S['tts_by_voice'] = {v: dict(language=next(r['language'] for r in real if r['voice'] == v),
                                 naturalness=round(statistics.mean(r['naturalness_1to5'] for r in real if r['voice'] == v), 2),
                                 prosody=round(statistics.mean(r['prosody_1to5'] for r in real if r['voice'] == v), 2))
                         for v in sorted({r['voice'] for r in real})}
    S['tts_wrong'] = [dict(case=r['case_id'], text=r['text'], heard=r['heard'], targets=[t for t in r['targets'] if t['result'] != 'correct'],
                           artifacts=r.get('artifacts'), comment=r.get('comment'))
                      for r in real if any(t['result'] != 'correct' for t in r['targets'] if r['kind'] != 'natural')]
    S['tts_artifacts'] = [dict(case=r['case_id'], artifacts=r['artifacts']) for r in real if r.get('artifacts')]

    asr_path = RESULTS / 'ext_asr_judge.json'
    if asr_path.exists():
        rows = json.loads(asr_path.read_text(encoding='utf-8'))
        diffs = [d for r in rows for d in (r.get('adjudication') or {}).get('differences', [])]
        S['asr_adjudication'] = dict(clips=len(rows), clips_with_differences=sum(1 for r in rows if r.get('adjudication')),
                                     differences=len(diffs), **{v: sum(d['verdict'] == v for d in diffs)
                                                                 for v in ('system_error', 'reference_error', 'equivalent', 'unclear')},
                                     reference_mismatch_clips=sum(1 for r in rows if (r.get('adjudication') or {}).get('reference_matches_audio') is False))
        # LLM-adjusted WER: score Pulse against the judge's best transcript only where the judge says the reference is wrong.
        by_lang = {}
        for r in rows:
            if not r['reference']:
                continue
            adj = r.get('adjudication') or {}
            ref2 = adj.get('best_transcript') if adj.get('reference_matches_audio') is False and adj.get('confidence') == 'high' else r['reference']
            by_lang.setdefault(r['language'], {'orig': [], 'adj': [], 'blind': []})
            by_lang[r['language']]['orig'].append(score(r['reference'], r['hypothesis']))
            by_lang[r['language']]['adj'].append(score(ref2, r['hypothesis']))
            by_lang[r['language']]['blind'].append(score(r['reference'], r['blind']))
        S['asr_wer_original_vs_llm_adjusted'] = {
            lang: dict(clips=len(v['orig']), wer_original=round(corpus(v['orig'])['wer'], 4),
                       wer_llm_adjusted=round(corpus(v['adj'])['wer'], 4), gemini_blind_wer_vs_reference=round(corpus(v['blind'])['wer'], 4))
            for lang, v in sorted(by_lang.items())}
        # LLM-adjudicated DIAGNOSTIC error rate (not WER, not ground truth): only differences the judge calls system_error, per reference word.
        S['asr_llm_adjudicated_diagnostic_error_rate'] = {}
        for key in ('language', 'condition'):
            for value in sorted({r[key] for r in rows if r['reference']}):
                part = [r for r in rows if r['reference'] and r[key] == value]
                words = sum(len(normalize(r['reference']).split()) for r in part)
                errs = sum(1 for r in part for d in (r.get('adjudication') or {}).get('differences', []) if d['verdict'] == 'system_error')
                equiv = sum(1 for r in part for d in (r.get('adjudication') or {}).get('differences', []) if d['verdict'] == 'equivalent')
                S['asr_llm_adjudicated_diagnostic_error_rate'][f'{key}={value}'] = dict(
                    clips=len(part), reference_words=words, raw_wer=round(corpus([score(r['reference'], r['hypothesis']) for r in part])['wer'], 4),
                    system_error_spans=errs, equivalent_spans=equiv, llm_adjudicated_diagnostic_error_rate=round(errs / words, 4))
        S['asr_system_error_examples'] = [dict(clip=r['clip_id'], language=r['language'], condition=r['condition'], **d)
                                          for r in rows for d in (r.get('adjudication') or {}).get('differences', [])
                                          if d['verdict'] == 'system_error'][:80]
        silent = [r for r in rows if not r['reference']]
        S['asr_no_speech_judge'] = [dict(clip=r['clip_id'], gemini_no_speech=r['blind_no_speech'], pulse=r['hypothesis']) for r in silent]
    (RESULTS / 'ext_judge_summary.json').write_text(json.dumps(S, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in S.items():
        print(f'== {k}', json.dumps(v, ensure_ascii=False)[:700])


if __name__ == '__main__':
    {'tts': tts, 'calibrate': calibrate, 'asr': asr, 'summary': summary}[sys.argv[1]]()
