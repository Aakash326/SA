# Smallest.ai Waves API — QA test suite

Small, reproducible evaluation of the Waves speech APIs as a customer integrates them:
Pulse STT (REST + WebSocket) and Lightning v3.1 Pro TTS (REST + WebSocket + SSE).
Engineering behaviour (contract, stream lifecycle, errors, limits) is the primary layer;
a compact ASR/TTS correctness suite supports it. Plan and rationale: `IMPLEMENTATION_STAGES.md`.
Documented contract used as the oracle: `docs/contract_notes.md`.

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows Git Bash; use bin/activate elsewhere
pip install -r requirements.txt                      # requests, websockets; ffmpeg/ffprobe on PATH
cp .env.example .env                                 # then put your key in .env — never commit it
python scripts/env_check.py
```

## Run order (each step appends JSONL evidence to `results/`)

| Stage | Command | Output |
|---|---|---|
| 1 smoke | `python scripts/smoke.py` | `smoke.jsonl`, `smoke/hello.wav` |
| 2 data | `python scripts/prepare_data.py` · `python scripts/make_prompts.py` | `templates/*.csv`, `clips/` |
| 3 ASR REST | `python scripts/asr_rest.py templates/clips.csv pulse` · `… pulse-pro --cohort english,no_speech --run asr_rest_pulse_pro` | `asr_rest*.jsonl` |
| 3 ASR language probe | `python scripts/asr_rest.py templates/clips.csv pulse --language-override multi-indic --run asr_lang_probe` | `asr_lang_probe.jsonl` |
| 3 ASR stream | `python scripts/asr_stream.py clips/EN05.wav en` (repeat per paired clip) | `asr_stream.jsonl` |
| 3 score | `python scripts/score_asr.py` | `asr_scores.csv`, `asr_summary.json` |
| 4 TTS | `python scripts/tts_rest.py templates/tts_prompts.csv` · `… challenge_prompts.csv --out challenge --run tts_challenge` | `tts/*.wav`, `challenge/*.wav` |
| 4 screen | `python scripts/tts_screen.py templates/tts_prompts.csv tts` · `… challenge_prompts.csv challenge --stream` (`--rescore` = no API calls) | `screen_*.csv` |
| 4 listen | `python scripts/make_listen_page.py`, open `results/listen.html`, save `results/listening_filled.csv` | human verdicts |
| 5 TTS stream | `python scripts/tts_ws.py --repeat 5` · `python scripts/tts_ws.py --sse 3` | `tts_ws.jsonl`, `tts_ws/*.wav` |
| 5–6 lifecycle | `python scripts/lifecycle.py` | `lifecycle.jsonl`, `concurrency.jsonl` |
| 6 negative | `python scripts/negative.py` | `negative.jsonl` |
| 6 docs | `python scripts/docs_checks.py` | `docs_checks.jsonl`, `voices.json` |
| 7 repeats | `python scripts/probe_en05.py` · `probe_tail.py` · `probe_nospeech.py` · `numeric_extension.py` | `probe_*.jsonl` |
| 8 report | `python scripts/build_report.py` | `summary.json`, `findings.md`, word count |

Stage 9 extension (wider languages/conditions, latency study, Gemini judge): see `EXTENSION_REPORT.md`
for results and the exact command sequence. It needs `GEMINI_API_KEY` in `.env`.

All calls are sequential except the single controlled overlap in `lifecycle.py` (R01).
STT requests are spaced 2.6 s apart to stay under the documented 25 requests/minute.

## Evidence conventions

- Each JSONL row: UTC and IST timestamps, host, endpoint, redacted request, status, kept response headers
  (`x-request-id`, `x-session-id`, rate-limit headers), body excerpt, client elapsed ms (monotonic clock),
  input SHA-256. `common.redact()` strips the key from everything written.
- Client latency is end-to-end from this machine; it is not server inference time.
- "Automated provisional" TTS verdicts come from Pulse transcribing Lightning output; they are not
  listening results. Human verdicts live only in `results/listening_filled.csv`.
- `results/_interrupted/` holds rows from a run stopped mid-way; they are kept but not scored.

## Data and licences

ASR clips are copied byte-identical (hash-checked) from the earlier licensed corpus:
Google SVQ (CC-BY-4.0), MUCS 2021 / OpenSLR 104 (CC-BY-SA-4.0), MUSAN (public-domain free-sound subset),
generated silence. No customer or private call audio is used. TTS prompts are authored, fictional values.
