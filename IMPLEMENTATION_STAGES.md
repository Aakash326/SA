# Smallest.ai Waves API QA — implementation stages

Assignment: Smallest.ai Round 3 product trial, area **APIs**. Primary layer is engineering
behaviour (contract, stream lifecycle, failure semantics, latency, limits). Secondary layer
is a compact ASR/TTS correctness suite used as supporting evidence. Final output is a
report of at most 1,500 words pasted into the hiring form, backed by a reproducible suite.

Source guide: `SmallestAI_Waves_API_QA_Testing_and_Repo.docx` (prepared 16 Nov 2026).
Documentation contract re-read on 16 Nov 2026; see `docs/contract_notes.md`.

## Ground rules (apply to every stage)

- The API key lives only in `.env` (git-ignored). No script prints it; logs store a
  redacted header.
- Every request writes one JSONL row: IST timestamp, UTC timestamp, endpoint, host,
  model, redacted request, status, response excerpt, request/session IDs, client
  elapsed time (monotonic clock), input SHA-256.
- All calls are sequential, except the single controlled overlap in stage 6.
  STT is paced under the documented 25 requests/minute per model.
- Observed fact, reproduced issue and hypothesis are kept as separate labels.
  A surprising result is repeated at least 3 times before it becomes a finding.
- No number, ID, timestamp or listening verdict is written into the report unless a
  saved artifact backs it. Human listening fields stay blank until a person fills them.

## Changes made to the guide's plan, and why

| # | Guide says | Change | Reason |
|---|---|---|---|
| 1 | Telugu cohort with ISO language codes | Probe `language=te` and `language=multi-indic` separately; score Telugu under whichever the API accepts | Pre-recorded `language` enum in the reference has no `te`; `multi-indic` is documented as India-region only |
| 2 | TTS WebSocket idle test with `?timeout=5` | Run it as an undocumented-parameter probe, with a plain idle socket as control | `timeout`, ping/pong and close codes are documented for Pulse, not for the TTS socket |
| 3 | Concurrency: expect 1 active synthesis and a 429 | Keep the single overlap; record result against both documented numbers | Limits page says 1 per account; Pro model card says "Concurrency (Standard Plan) 10" |
| 4 | E04 wrong voice+language pair | Record against both documented behaviours | Synthesize page says mismatches return 400; Pro model card says the API does not reject them |
| 5 | Six targeted ASR challenge cases | Generated with Lightning TTS and scored as a separate **synthetic round-trip** cohort | No consented human recordings exist for these exact phrases; synthetic speech must not be pooled with human WER |
| 6 | Code-switched cohort | Public MUCS Hindi-English clips, not the internal call recordings | Internal calls are private; the Gnani submission excluded them for the same reason |
| 7 | — | Add an SSE parity check (3 requests) | WS and SSE use different schemas (`data.audio` vs top-level `audio`); cheap contract check |
| 8 | — | Add docs-consistency checks D02–D05 (default model, `Accept` vs `output_format`, voices endpoint path, WS auth query parameter) | Each documented contradiction is settled with 1–2 requests |
| 9 | Optional pulse-pro English cohort | Included (6 English clips) | Pulse Pro is the only path that returns `request_id`; needed for evidence fields |

## Stage 0 — workspace and contract capture

- Folder layout: `clips/`, `templates/`, `scripts/`, `results/`, `docs/`.
- `.env`, `.env.example`, `.gitignore`, `requirements.txt`.
- `docs/contract_notes.md`: the documented contract and the list of documented
  contradictions, each with page URL.
- `results/environment.json`: OS, Python, library and ffmpeg versions, public egress
  region (resolved host IPs for `api.smallest.ai`), date.

Exit: `python scripts/env_check.py` prints dependency versions and "key present".

## Stage 1 — smoke tests (guide §5)

- One Lightning v3.1 Pro REST request (`meher`, 24 kHz WAV); verify RIFF header,
  sample rate and duration with `ffprobe`.
- One Pulse REST request with a known 16 kHz clip.
- Record response headers once in full (to learn which request-ID headers exist).

Exit: playable `results/smoke/hello.wav`, one transcript, both raw responses saved.

## Stage 2 — datasets (guide §4)

ASR manifest `templates/clips.csv`, 24 speech clips + 3 no-speech controls, copied from
the existing licensed corpus and re-hashed:

| Cohort | Clips | Source | Reference status |
|---|---|---|---|
| English | 6 | Google SVQ (CC-BY-4.0) | 6 listener-confirmed |
| Hindi | 6 | Google SVQ | 5 listener-confirmed, 1 dataset text |
| Telugu | 6 | Google SVQ | 5 listener-confirmed, 1 dataset text |
| Hindi-English code-switch | 6 | MUCS 2021 / OpenSLR 104 (CC-BY-SA-4.0) | dataset text |
| No-speech | 3 | 1 generated silence, 2 MUSAN noise | empty by construction |

Columns: `clip_id, path, language, api_language, split, reference, reference_status,
speaker_id, condition, critical_slots, source, license, sha256, duration_s`.
Every file is verified as mono, 16 kHz, signed 16-bit with `ffprobe`.

TTS manifest `templates/tts_prompts.csv`, 16 prompts (4 money/signs, 4 IDs/leading
zeros, 4 dates/times/acronyms, 4 negation/mixed language) with expected targets and
accepted/rejected readings, plus 4 raw-vs-expanded pairs (T02).

Synthetic challenge manifest `templates/challenge_prompts.csv`, 6 phrases
(1,499 vs 1,999, "zero zero seven zero", "do not sell", 9:05 vs 9:50, KYC/UCC/IPO).

Exit: manifests validate; no clip is missing or mis-formatted.

## Stage 3 — ASR quality (A01–A04)

- A01 `asr_rest.py`: 24 clips on `pulse`; 6 English clips again on `pulse-pro`
  (separate cohort). Telugu language-code probe first.
- A02 critical slots: exact-match scoring of amounts, years, names and negation.
- A03 no-speech controls: any substantive output logged as false transcription
  (WER undefined, reported separately), plus the documented `NO_SPEECH_DETECTED` path.
- A04 `asr_stream.py`: 6 of the same clips over `wss://…/stt/live`, raw PCM without the
  WAV header, real-time paced; final transcript built only from `is_final=true`
  segments; waits for `is_last=true` after `close_stream`.
- `score_asr.py`: corpus-weighted WER/CER per language, raw and normalized; paired
  REST-vs-WebSocket WER on the 6 shared clips.

Metric policy (same module as the Gnani evaluation): NFC, case folding, Unicode digits
mapped, punctuation removed, decimal/time separators and minus kept. CER reported with
and without spaces. Vendor's suggested `whisper_normalizer` is not used; stated as a
limitation.

Exit: `results/asr_scores.csv`, `results/asr_summary.json`.

## Stage 4 — TTS quality (T01–T02)

- T01 `tts_rest.py`: 16 prompts, sequential, WAV 24 kHz, hashes and headers saved.
- T02: raw vs expanded pairs kept as separate scores.
- `tts_screen.py`: each WAV is transcribed with Pulse and checked against target
  rules. Labelled **automated provisional**, never "human verified".
- `make_listen_page.py`: `results/listen.html` with every prompt, expected target,
  audio player and pass/fail/ambiguous controls that export a CSV. A human must
  complete this before any strict target accuracy is reported.
- Synthetic round-trip cohort: 6 challenge phrases synthesized, then transcribed.

Exit: 16 + 8 + 6 WAVs, provisional table, listening page ready.

## Stage 5 — streaming engineering (S01–S03)

- S01 `tts_ws.py`: every frame logged with a monotonic arrival time. Per run:
  handshake ms, first-audio ms, complete ms, chunk count, inter-chunk gaps, audio
  duration from PCM bytes, simulated playback underrun with a 200 ms start buffer.
- Repeatability: 1 short and 1 long prompt, 5 sequential runs each (n=5 stated).
- SSE parity: 3 runs of the short prompt; schema and terminal event compared to WS.
- S02 STT `finalize` vs `close_stream`: `finalize` must yield `is_final=true` with
  `from_finalize=true` and no `is_last`; socket must stay usable.
- S03 lifecycle: STT ping/pong (documented); TTS idle socket, TTS `?timeout=5` probe
  and TTS ping probe (undocumented, observation only); client cancel mid-stream;
  behaviour after `complete` (docs say the server closes the socket).

Exit: `results/tts_ws_runs.csv`, per-run frame logs, lifecycle log.

## Stage 6 — validation, limits, reliability (E01–E06, R01–R02, D01–D05)

Negative matrix, one request each, repeated 3 times only where the result is
surprising:

| ID | Input | Documented expectation |
|---|---|---|
| E01 | Missing key / invalid key (REST TTS, REST STT, WS handshake) | 401; no secret echoed |
| E02 | Unknown `voice_id` | 400 with a descriptive message |
| E03 | Missing `text`; whitespace-only text; invalid `model` | 400 |
| E04 | English voice with `language=hi`, Hindi voice with `language=en` | 400 **or** not rejected (docs disagree) |
| E05 | Malformed JSON on TTS WebSocket | interpretable error or close (shape undocumented) |
| E06 | `sample_rate=12345` (TTS); STT WS `sample_rate` mismatch | 400 or documented behaviour |
| E07 | STT: missing `model`, `pulse-pro` on WebSocket, empty body, non-audio bytes | 400 with `code`/`error_code` |

- R01 one controlled overlap: one long request, one second request while active;
  then one retry after completion. Compared with both documented limits.
- R02 disconnect mid-stream, then a fresh connection and request.
- D01–D05 docs consistency: quickstart commands as written; default model when
  omitted; `Accept` header vs `output_format` default; both voices endpoint paths;
  `meher` language tags.

Not done: load generation, fuzzing, security probing, multi-account limit bypass.

Exit: `results/negative.jsonl`, `results/concurrency.jsonl`, `results/docs_checks.jsonl`.

## Stage 7 — repeat and classify (guide §10)

- Each surprising behaviour is re-run 3 times in a fresh process, with a passing
  control beside it.
- `build_report.py` produces `results/summary.json` and `results/findings.csv` with
  one evidence packet per finding: test ID, endpoint/model/voice, input hash, redacted
  reproduction, documented expectation with URL, observed status/body/close code,
  IDs, IST window, reproduction rate, impact, workaround, acceptance test.
- Severity uses the guide's P0–P3 rubric, chosen from observed impact only.

## Stage 8 — report

- `qa_report_draft.md` in the exact hiring-form field order, under 1,500 words, with a
  word counter in `build_report.py`.
- `README.md`: how to reproduce every number.
- Pre-submission checklist from guide §12, including a scan of all outputs for the key.

## Stage 9 — Gnani-style extension (separate cohort, never pooled with stages 1–8)

Requested after the focused trial: broader languages and conditions, latency/RTF study, naturalness and
prosody, and LLM-assisted verification of both ASR references and TTS audio. Results are reported as an
extension, labelled as such, and do not change the headline numbers above.

| Block | What | Size | Output |
|---|---|---|---|
| X-ASR-1 languages | Unused licensed SVQ clips: English, Hindi, Telugu, Tamil, Kannada, Marathi (clean + numbers); language-code probe for `ta`/`kn`/`mr` before the run | ~70 clips | per-language WER/CER |
| X-ASR-2 conditions | Real noise, synthetic SNR 20/10/0 dB pairs, telephone simulation (8 kHz, A-law, µ-law), inserted pauses, long FLEURS utterances | ~85 clips | WER by condition, paired deltas |
| X-ASR-3 streaming latency | 5 clips per language over WebSocket, incl. 8 kHz streaming of telephone clips | ~35 sessions | first partial, final-after-audio, REST RTF |
| X-ASR-4 LLM verification | Gemini blind transcript → reference check → per-difference adjudication (ASR error / reference error / equivalent) | every speech clip | LLM-adjusted WER beside the original |
| X-TTS-1 languages | 6 languages × 5 prompts (amount, leading-zero ID, date+time, negation, natural conversational) × 2 voices | 60 clips | per-language target accuracy |
| X-TTS-2 Gemini judge | Blind transcription first, then target check + naturalness 1–5 + prosody 1–5 + artifacts | 60 + controls | LLM-rated, not human MOS |
| X-TTS-3 judge calibration | Planted wrong-value audio (judge must say wrong) + the 20 human-passed clips (judge should agree) | 6 + 20 | judge miss / false-alarm rate |
| X-TTS-4 objective QC | Duration, level, near-full-scale samples, internal low-energy gaps, leading/trailing silence | all WAVs | flags only |
| X-LAT | Gnani report-4 protocol: 3 English lengths (~60 / ~400 / ~930 chars), REST vs SSE vs WebSocket cold vs WebSocket warm, 2 warm-ups excluded, 5 measured each | ~70 requests | TTFA, total, RTF medians |

Rules kept from the Gnani evaluation:
- Gemini is a listening assistant, never ground truth: blind first, cached by audio+prompt fingerprint,
  calibrated before use, and every LLM number is labelled "LLM-assessed".
- Human scores are never overwritten by LLM scores.
- Transformed clips (noise/codec) are paired measurements of the same utterance, not new speakers.
- Latency: TTFA = request sent → first decoded audio; RTF = elapsed / decoded audio seconds; warm WebSocket
  = request on an already-open socket; cold includes the handshake.

## Needs a human (cannot be automated)

1. Listening pass on `results/listen.html` (TTS strict target accuracy).
2. Listening confirmation of the 8 clips whose reference is dataset text only.
3. Actual hours spent, city/ISP line in Method, and the final paste into the form.
4. A second run on another day/network before escalating any latency observation.
