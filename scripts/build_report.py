"""Stage 7/8: aggregate every evidence log into results/summary.json and results/evidence.md,
and word-count the hiring-form draft.

usage: python scripts/build_report.py
Every number quoted in qa_report_draft.md should be traceable to a key in summary.json.
"""
import csv
import json
import re
import statistics

from common import RESULTS, ROOT, percentile, read_jsonl

S = {}


def med(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def window(rows):
    stamps = sorted(r['ts_ist'] for r in rows if r.get('ts_ist'))
    return [stamps[0][:19] + ' IST', stamps[-1][:19] + ' IST'] if stamps else None


# ---- environment & volume
S['environment'] = json.loads((RESULTS / 'environment.json').read_text(encoding='utf-8'))
logs = {p.stem: read_jsonl(p.stem) for p in RESULTS.glob('*.jsonl')}
S['volume'] = {name: len(rows) for name, rows in sorted(logs.items())}
S['volume']['total_logged_calls'] = sum(len(r) for r in logs.values())
S['test_window_ist'] = window([r for rows in logs.values() for r in rows])

# ---- ASR
S['asr'] = json.loads((RESULTS / 'asr_summary.json').read_text(encoding='utf-8'))
rest = logs.get('asr_rest', [])
S['asr_rest_latency'] = dict(n=len(rest), median_ms=med([r['elapsed_ms'] for r in rest]),
                             p95_ms=percentile([r['elapsed_ms'] for r in rest], 0.95),
                             statuses=sorted({r['status'] for r in rest}))
a04 = [r for r in logs.get('asr_stream', []) if r.get('test') == 'A04']
S['asr_stream'] = dict(
    sessions=len(a04), is_last_received=sum(1 for r in a04 if r.get('n_is_last') == 1),
    timeouts=sum(1 for r in a04 if r.get('timeout_waiting_is_last')),
    close_codes=sorted({str(r.get('close_code')) for r in a04}),
    handshake_median_ms=med([r.get('handshake_ms') for r in a04]),
    first_text_median_ms=med([r.get('first_text_ms') for r in a04 if r.get('first_text_ms')]),
    final_after_last_audio_median_ms=med([r.get('final_after_last_audio_ms') for r in a04]),
    final_after_last_audio_max_ms=max((r.get('final_after_last_audio_ms') or 0) for r in a04) if a04 else None)

en05_ws = [r for r in logs.get('asr_stream', []) if r.get('clip') == 'EN05' and 'transcript' in r]
en05_rest = [r for r in logs.get('asr_rest', []) + logs.get('probe_en05', []) if r.get('clip_id') == 'EN05' or r.get('test') == 'P-EN05-REST']
S['finding_en05'] = dict(
    reference='Who was the leader of Switzerland in 1499?',
    ws_runs=[dict(tag=r['test'], params={k: v for k, v in r['params'].items() if k not in ('model', 'encoding', 'sample_rate')},
                  frame_ms=r.get('frame_ms'), paced=r.get('paced'), transcript=r['transcript'], session=r.get('session_ids'),
                  ts=r['ts_ist']) for r in en05_ws],
    ws_1999=sum(1 for r in en05_ws if '1999' in r['transcript']),
    ws_1499=sum(1 for r in en05_ws if '1499' in r['transcript'] or 'fourteen ninety' in r['transcript'].lower()),
    rest_runs=[dict(transcript=r.get('transcript'), ts=r['ts_ist'], request_id=(r.get('headers') or {}).get('x-request-id')) for r in en05_rest],
    window=window(en05_ws + en05_rest))
ext = logs.get('numeric_extension', [])
S['numeric_extension'] = dict(clips=len(ext), rest_digits_exact=sum(r['rest_numbers_ok'] for r in ext),
                              ws_digits_exact=sum(r['ws_numbers_ok'] for r in ext),
                              rows=[dict(clip=r['clip_id'], ref=r['reference'], rest=r['rest'], ws=r['ws']) for r in ext])

ns = logs.get('probe_nospeech', []) + [dict(clip=r['clip_id'], model=r['model'], transcript=r.get('transcript'),
                                            request_id=(r.get('body') or {}).get('request_id'), ts_ist=r['ts_ist'])
                                       for r in logs.get('asr_rest', []) + logs.get('asr_rest_pulse_pro', [])
                                       if r.get('cohort') == 'no_speech']
S['no_speech'] = {}
for model in ('pulse', 'pulse-pro'):
    part = [r for r in ns if r['model'] == model]
    S['no_speech'][model] = dict(requests=len(part), non_empty=sum(1 for r in part if (r.get('transcript') or '').strip()),
                                 outputs=sorted({(r.get('transcript') or '') for r in part}),
                                 examples=[dict(clip=r['clip'], transcript=r.get('transcript'), request_id=r.get('request_id'),
                                                ts=r['ts_ist']) for r in part if (r.get('transcript') or '').strip()][:6],
                                 window=window(part))

probe = logs.get('asr_lang_probe', [])
te_multi = [r for r in probe if r['params']['language'] == 'multi-indic' and r['cohort'] == 'telugu']


def script_of(text):
    names = set()
    for ch in text:
        cp = ord(ch)
        names |= {'telugu'} if 0x0C00 <= cp <= 0x0C7F else {'devanagari'} if 0x0900 <= cp <= 0x097F else \
            {'gujarati'} if 0x0A80 <= cp <= 0x0AFF else {'bengali'} if 0x0980 <= cp <= 0x09FF else \
            {'odia'} if 0x0B00 <= cp <= 0x0B7F else {'latin'} if ch.isascii() and ch.isalpha() else set()
    return sorted(names)


S['multi_indic_telugu'] = dict(clips=len(te_multi), telugu_script=sum(1 for r in te_multi if script_of(r['transcript'] or '') == ['telugu']),
                               scripts=[dict(clip=r['clip_id'], scripts=script_of(r['transcript'] or ''), text=r['transcript']) for r in te_multi],
                               with_te=S['asr'].get('rest:pulse:language=te', {}).get('telugu'))
en_multi = [r for r in probe if r['params']['language'] == 'multi-indic' and r['cohort'] == 'english']
S['multi_indic_english_non_latin'] = [dict(clip=r['clip_id'], text=r['transcript']) for r in en_multi
                                      if set(script_of(r['transcript'] or '')) - {'latin'}]

# ---- TTS quality (provisional + human if present)
screen = list(csv.DictReader(open(RESULTS / 'screen_tts.csv', encoding='utf-8-sig')))
core = [r for r in screen if r['category'] != 'expanded_pair']
S['tts_screen'] = dict(prompts=len({r['case_id'] for r in core}), targets=len(core),
                       auto_pass=sum(1 for r in core if r['automated_provisional'] == 'auto_pass'),
                       expanded_pairs=len({r['case_id'] for r in screen if r['category'] == 'expanded_pair'}),
                       label='automated provisional: Pulse transcription of Lightning audio, not a listening result')
human_file = RESULTS / 'listening_filled.csv'
if human_file.exists():
    human = [r for r in csv.DictReader(open(human_file, encoding='utf-8-sig')) if r['human_verdict']]
    S['tts_human'] = dict(listeners=sorted({r['listener'] for r in human}), judged=len(human),
                          passed=sum(1 for r in human if r['human_verdict'] == 'pass'),
                          failed=[r for r in human if r['human_verdict'] == 'fail'],
                          unclear=sum(1 for r in human if r['human_verdict'] == 'unclear'))
else:
    S['tts_human'] = 'NOT YET DONE — open results/listen.html'
rest_tts = logs.get('tts_rest', [])
S['tts_rest_latency'] = dict(n=len(rest_tts), median_ms=med([r['elapsed_ms'] for r in rest_tts]),
                             max_ms=max(r['elapsed_ms'] for r in rest_tts), all_wav=all(r.get('wav') for r in rest_tts))

# ---- TTS streaming
ws_rows = [r for r in logs.get('tts_ws', []) if r['test'] in ('S01-short', 'S01-long')]
tail_rows = [r for r in logs.get('tts_ws', []) if r.get('complete_ms') and r.get('frames') and r['test'] != 'S01-SSE']


def tail(r):
    audio = [f['t_ms'] for f in r['frames'] if f.get('audio_bytes')]
    return round(r['complete_ms'] - audio[-1], 1) if audio else None


S['tts_ws'] = {}
for name in ('S01-short', 'S01-long'):
    part = [r for r in ws_rows if r['test'] == name]
    S['tts_ws'][name] = dict(n=len(part), audio_s_median=med([r['audio_s'] for r in part]),
                             handshake_median_ms=med([r['handshake_ms'] for r in part]),
                             first_audio_median_ms=med([r['first_audio_ms'] for r in part]),
                             first_audio_max_ms=max(r['first_audio_ms'] for r in part) if part else None,
                             last_audio_median_ms=med([r['complete_ms'] - tail(r) for r in part]),
                             complete_median_ms=med([r['complete_ms'] for r in part]),
                             gap_max_ms=max(r['gap_max_ms'] for r in part) if part else None,
                             underruns_200ms=sum(r['playout_200']['underruns'] for r in part),
                             server_closed_after_complete=sum(1 for r in part if r.get('server_closed_within_s')))
tails = [t for t in (tail(r) for r in tail_rows) if t is not None]
S['finding_tail'] = dict(ws_runs=len(tails), tail_median_ms=med(tails), tail_min_ms=min(tails), tail_max_ms=max(tails),
                         variants={v: [r['tail_ms'] for r in logs.get('probe_tail', []) if r.get('variant') == v]
                                   for v in sorted({r.get('variant') for r in logs.get('probe_tail', []) if r.get('variant')})},
                         slot_free_during_tail=[dict(probe=r['probe'], second=(r['second'] or {}).get('status', (r['second'] or {}).get('ok')))
                                                for r in logs.get('probe_tail', []) if r['test'] == 'TAIL-slot'],
                         example_request_ids=[r['request_ids'][0] for r in ws_rows[:3] if r.get('request_ids')],
                         window=window(tail_rows))
sse = [r for r in logs.get('tts_ws', []) if r['test'] == 'S01-SSE']
S['tts_sse'] = dict(n=len(sse), first_audio_median_ms=med([r['first_audio_ms'] for r in sse]),
                    done_median_ms=med([r['complete_ms'] for r in sse]), done_seen=sum(r['done_seen'] for r in sse))

# ---- lifecycle / concurrency / negative / docs
S['lifecycle'] = [{k: v for k, v in r.items() if k not in ('ts_utc', 'host', 'events', 'ping_events')}
                  for r in logs.get('lifecycle', [])]
S['concurrency'] = [dict(run=r['run'], variant=r['variant'], active=r['active']['status'], overlap=r['overlap']['status'],
                         overlap_body=r['overlap'].get('body'), overlap_headers=r['overlap'].get('headers'),
                         retry=(r['retry'] or {}).get('status'), retry_inclusive_ms=r['retry_inclusive_ms'], ts=r['ts_ist'])
                    for r in logs.get('concurrency', [])]
S['negative'] = [dict(test=r['test'], note=r['note'], expected=r['expected'],
                      observed=r.get('status') or r.get('handshake_status') or r.get('handshake'),
                      body=(r.get('body') or json.dumps(r.get('messages', [])[:2], ensure_ascii=False))[:220],
                      close=r.get('close'), key_leak=r.get('key_material_in_response'),
                      request_id=(r.get('headers') or {}).get('x-request-id'), ts=r['ts_ist'])
                 for r in logs.get('negative', [])]
S['docs_checks'] = [dict(test=r['test'], note=r.get('note'), status=r['status'], content_type=(r.get('headers') or {}).get('content-type'),
                         wav=r.get('wav'), voice_count=r.get('voice_count')) for r in logs.get('docs_checks', [])]

misc = logs.get('probe_misc', [])
S['finding_finalize_dup'] = [dict(clip=r['clip'], control=r['control'], finalize=r['finalize'], segments=r['segments'],
                                  session=r['sessions'], ts=r['ts_ist'],
                                  duplicated=r['finalize'].split() != r['control'].split() and len(r['finalize'].split()) > len(r['control'].split()))
                             for r in misc if r['test'] == 'P-FINALIZE-pair']
S['zero_audio_close_stream'] = [dict(language=r['language'], transcript=r['transcript'],
                                     session=(r['messages'] or [{}])[0].get('session_id'), ts=r['ts_ist'])
                                for r in misc if r['test'] == 'P-ZERO-AUDIO']
stream_all = [r for r in logs.get('asr_stream', []) if 'close_code' in r]
S['close_codes'] = dict(
    stt_after_is_last={str(c): sum(1 for r in stream_all if str(r['close_code']) == str(c)) for c in {r['close_code'] for r in stream_all}},
    stt_idle_timeout=[r['close'] for r in logs.get('lifecycle', []) if r['test'] == 'S03-STT-timeout'],
    tts_idle=[dict(query=r['query'], close=r['close'], message=[e.get('message') for e in r['events'] if e.get('message')])
              for r in logs.get('lifecycle', []) if r['test'] == 'S03-TTS-idle'],
    tts_server_closed_after_complete=sum(1 for r in logs.get('tts_ws', []) if r.get('server_closed_within_s')),
    tts_runs_checked=sum(1 for r in logs.get('tts_ws', []) if 'server_closed_within_s' in r))
neg = logs.get('negative', [])
S['auth'] = dict(rejections=[(r['note'], r.get('status') or r.get('handshake_status')) for r in neg if r['test'] == 'E01'],
                 key_leaks=sum(1 for r in neg if r.get('key_material_in_response')))
S['error_shapes'] = sorted({json.dumps(r.get('body_fields')) for r in neg if r.get('status') and r['status'] >= 400})

(RESULTS / 'summary.json').write_text(json.dumps(S, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
print('summary.json written;', S['volume']['total_logged_calls'], 'logged rows; window', S['test_window_ist'])

draft = ROOT / 'qa_report_draft.md'
if draft.exists():
    body = re.sub(r'<!--.*?-->', '', draft.read_text(encoding='utf-8'), flags=re.S)
    words = len(re.findall(r"[\w₹%][\w'’.,:/%₹-]*", body))
    print(f'qa_report_draft.md: {words} words (limit 1500)')
