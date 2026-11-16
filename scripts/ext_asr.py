"""Stage 9 X-ASR-1..3: broader languages and conditions, REST on every clip, WebSocket on a subset.

usage: python scripts/ext_asr.py prepare      # write templates/ext_clips.csv, copy clips to clips/ext2/
       python scripts/ext_asr.py rest         # Pulse REST on every clip (resumable)
       python scripts/ext_asr.py stream       # Pulse WebSocket on the streaming subset (resumable)
       python scripts/ext_asr.py score        # results/ext_asr_scores.csv + ext_asr_summary.json

Clips: unused licensed SVQ / FLEURS / MUSAN items from ../gnani. None overlap templates/clips.csv or the earlier
numeric extension. Transformed clips (noise, codec, pauses) keep their parent id and are paired measurements.
"""
import asyncio
import csv
import json
import shutil
import sys
import time

import requests

from asr_stream import stream
from common import HTTP, RESULTS, ROOT, Clock, auth, body_excerpt, headers_of, log, read_jsonl, sha256, wav_info
from metrics import corpus, score

GNANI = ROOT.parent / 'gnani'
MANIFEST = ROOT / 'templates' / 'ext_clips.csv'
LANG = {'en-IN': 'en', 'hi-IN': 'hi', 'te-IN': 'te', 'ta-IN': 'ta', 'kn-IN': 'kn', 'mr-IN': 'mr'}
CATEGORIES = ('clean_en', 'clean_hi', 'clean_te', 'clean_ta', 'clean_kn', 'clean_mr', 'numbers', 'real_noise',
              'synthetic_noise', 'telephony_sim', 'pause', 'long', 'no_speech')
EARLIER_EXT = {'NUM-EN-02', 'EXP-NUM-EN-01', 'EXP-NUM-EN-02', 'EXP-NUM-EN-03', 'EXP-NUM-EN-04', 'EXP-NUM-EN-05', 'EXP-NUM-EN-06'}


def condition(row):
    cat = row['category']
    if cat.startswith('clean_'):
        return 'clean'
    if cat == 'synthetic_noise':
        return 'snr_' + row['clip_id'].rsplit('-', 1)[-1] + 'db'
    if cat == 'telephony_sim':
        return 'tel_' + row['clip_id'].rsplit('-', 1)[-1].lower()
    return cat


def prepare():
    used = {r['source_clip_id'] for r in csv.DictReader(open(ROOT / 'templates' / 'clips.csv', encoding='utf-8-sig'))} | EARLIER_EXT
    out = []
    (ROOT / 'clips' / 'ext2').mkdir(parents=True, exist_ok=True)
    for r in csv.DictReader(open(GNANI / 'data' / 'asr_manifest.csv', encoding='utf-8-sig')):
        if r['clip_id'] in used or r['category'] not in CATEGORIES or not r['input_path']:
            continue
        if not r['source_dataset'].startswith(('google', 'MUSAN', 'generated')):
            continue  # private call audio is never used
        src = GNANI / r['input_path']
        dst = ROOT / 'clips' / 'ext2' / f"{r['clip_id']}.wav"
        shutil.copyfile(src, dst)
        if sha256(dst) != r['input_sha256']:
            raise SystemExit(f"hash mismatch {r['clip_id']}")
        info = wav_info(dst.read_bytes()) or {}
        language = r['language'].split(',')[0]
        out.append(dict(clip_id=r['clip_id'], path=f"clips/ext2/{r['clip_id']}.wav", language=language,
                        api_language=LANG.get(language, 'en'), category=r['category'], condition=condition(r),
                        reference=r['reference_transcript'], reference_origin=r['reference_origin'],
                        human_reference_verified=r['human_reference_verified'], speaker_id=r['speaker_id'],
                        source=r['source_dataset'], license=r['license_or_consent'], derivation=r['derivation_json'],
                        sha256=r['input_sha256'], duration_s=r['duration_s'], sample_rate=info.get('sample_rate'),
                        format_code=info.get('format_code'), bits=info.get('bits')))
    with open(MANIFEST, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    by = {}
    for r in out:
        by.setdefault((r['language'] or 'none', r['condition']), 0)
        by[(r['language'] or 'none', r['condition'])] += 1
    print(len(out), 'clips;', sum(float(r['duration_s']) for r in out) / 60, 'minutes')
    for k, v in sorted(by.items()):
        print(' ', k, v)


def clips():
    return list(csv.DictReader(open(MANIFEST, encoding='utf-8-sig')))


def rest():
    done = {r['clip_id'] for r in read_jsonl('ext_asr_rest') if r.get('status') == 200}
    for c in clips():
        if c['clip_id'] in done:
            continue
        audio = (ROOT / c['path']).read_bytes()
        params = {'model': 'pulse', 'language': c['api_language']}
        for attempt in range(1, 4):
            clock = Clock()
            try:
                r = requests.post(f'{HTTP}/stt/', params=params, headers={**auth(), 'Content-Type': 'application/octet-stream'},
                                  data=audio, timeout=120)
            except requests.RequestException as error:
                log('ext_asr_rest', dict(test='X-ASR', clip_id=c['clip_id'], attempt=attempt, status=None, error=repr(error)[:200]))
                time.sleep(2 ** attempt)
                continue
            elapsed = clock.ms()
            body = r.json() if 'json' in r.headers.get('content-type', '') else {'_raw': body_excerpt(r)}
            log('ext_asr_rest', dict(test='X-ASR', clip_id=c['clip_id'], attempt=attempt, params=params, status=r.status_code,
                                     elapsed_ms=elapsed, headers=headers_of(r), input_sha256=c['sha256'],
                                     audio_duration_s=float(c['duration_s']), rtf=round(elapsed / 1000 / float(c['duration_s']), 4),
                                     transcript=body.get('transcription'), body=body))
            print(c['clip_id'], c['api_language'], r.status_code, elapsed, 'ms |', (body.get('transcription') or str(body))[:90])
            time.sleep(2.6)
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2 ** attempt)


def stream_subset():
    """Five clean clips per language at 16 kHz, plus the 8 kHz telephone clips streamed natively at 8 kHz."""
    picked, per = [], {}
    for c in clips():
        if c['condition'] == 'clean' and c['format_code'] == '1' and per.get(c['language'], 0) < 5:
            per[c['language']] = per.get(c['language'], 0) + 1
            picked.append((c, {}))
        if c['condition'] == 'tel_8k' and c['format_code'] == '1':
            picked.append((c, {}))
    done = {r['clip'] for r in read_jsonl('asr_stream') if str(r.get('test', '')).startswith('X-WS')}
    for c, extra in picked:
        if c['clip_id'] in done:
            continue
        out = asyncio.run(stream(ROOT / c['path'], c['api_language'], tag=f"X-WS-{c['condition']}"))
        print(c['clip_id'], c['condition'], 'first_text', out.get('first_text_ms'), 'final_after_audio',
              out.get('final_after_last_audio_ms'), '|', (out.get('transcript') or '')[:80])


def scoring():
    meta = {c['clip_id']: c for c in clips()}
    rest_rows = {}
    for r in read_jsonl('ext_asr_rest'):
        if r.get('status') == 200:
            rest_rows[r['clip_id']] = r
    ws_rows = {r['clip']: r for r in read_jsonl('asr_stream') if str(r.get('test', '')).startswith('X-WS') and 'transcript' in r}
    rows = []
    for clip_id, r in rest_rows.items():
        c = meta[clip_id]
        for transport, hyp in (('rest', r.get('transcript') or ''), ('ws', (ws_rows.get(clip_id) or {}).get('transcript'))):
            if hyp is None:
                continue
            s = score(c['reference'], hyp)
            rows.append(dict(clip_id=clip_id, transport=transport, language=c['language'] or 'none', condition=c['condition'],
                             category=c['category'], human_reference_verified=c['human_reference_verified'],
                             reference=c['reference'], hypothesis=hyp, rtf=r['rtf'] if transport == 'rest' else None,
                             elapsed_ms=r['elapsed_ms'] if transport == 'rest' else None, **s))
    with open(RESULTS / 'ext_asr_scores.csv', 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    rest_only = [r for r in rows if r['transport'] == 'rest']
    for key in ('language', 'condition'):
        for value in sorted({r[key] for r in rest_only}):
            part = [r for r in rest_only if r[key] == value and r['ref_word_count']]
            if part:
                c = corpus(part)
                summary[f'{key}={value}'] = dict(clips=len(part), words=c['reference_words'], wer=round(c['wer'], 4),
                                                 cer=round(c['cer'], 4), cer_no_spaces=round(c['cer_no_spaces'], 4))
    for lang in sorted({r['language'] for r in rest_only}):
        part = [r for r in rest_only if r['language'] == lang and r['condition'] == 'clean' and r['ref_word_count']]
        if part:
            c = corpus(part)
            summary[f'clean_language={lang}'] = dict(clips=len(part), words=c['reference_words'], wer=round(c['wer'], 4), cer=round(c['cer'], 4))
    silent = [r for r in rest_only if not r['ref_word_count']]
    summary['no_speech'] = dict(clips=len(silent), false_transcriptions=sum(1 for r in silent if r['false_transcription']))
    rtf = sorted(r['rtf'] for r in rest_only)
    summary['rest_rtf'] = dict(n=len(rtf), median=rtf[len(rtf) // 2], p95=rtf[int(len(rtf) * 0.95)] if rtf else None)
    lat = sorted(r['elapsed_ms'] for r in rest_only)
    summary['rest_latency_ms'] = dict(median=lat[len(lat) // 2], p95=lat[int(len(lat) * 0.95)])
    paired = [c for c in ws_rows if c in rest_rows]
    if paired:
        pr = [r for r in rows if r['clip_id'] in paired and r['ref_word_count']]
        summary['paired_rest_vs_ws'] = {t: dict(clips=len([r for r in pr if r['transport'] == t]),
                                                wer=round(corpus([r for r in pr if r['transport'] == t])['wer'], 4)) for t in ('rest', 'ws')}
        ws_list = [ws_rows[c] for c in paired]
        summary['ws_latency'] = dict(sessions=len(ws_list),
                                     first_text_median_ms=sorted(r['first_text_ms'] for r in ws_list if r.get('first_text_ms'))[len(ws_list) // 2],
                                     final_after_audio_median_ms=sorted(r['final_after_last_audio_ms'] for r in ws_list if r.get('final_after_last_audio_ms') is not None)[len(ws_list) // 2],
                                     is_last=sum(1 for r in ws_list if r.get('n_is_last') == 1))
    # Paired condition deltas: SNR and telephone variants against their clean parent where available.
    (RESULTS / 'ext_asr_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in summary.items():
        print(f'{k:32}', json.dumps(v, ensure_ascii=False))


if __name__ == '__main__':
    {'prepare': prepare, 'rest': rest, 'stream': stream_subset, 'score': scoring}[sys.argv[1]]()
