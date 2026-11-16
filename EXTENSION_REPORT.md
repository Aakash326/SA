# Stage 9 extension — wider languages, conditions, latency and LLM-assisted listening

Revised 16 November 2026 after two reviews ("Stage 9 Review & Fix Plan" and "Stage 9 Final Corrections").
Separate cohort from the focused trial; nothing here changes the headline numbers. Collected 16 November 2026,
21:05–21:47 IST (the §4 completion-gap cohort also includes focused-trial runs from 20:31 IST), from one
Windows 11 machine (Python 3.14.4, requests 2.34.2, websockets 17.4, google-genai 3.3.0) against
`api.smallest.ai` with automatic routing. Every number traces to a file named beside it. Documentation quotes
were re-read on 16 November 2026.

## 0. Classification of every claim

Each claim is one of: **documentation mismatch** (observed behaviour contradicts a quoted sentence in the docs),
**lifecycle inconsistency** (reproducible behaviour that matches no documented outcome),
**correctness/safety issue** (reproducible wrong output with no model-specific contract to cite),
**documentation gap** (works but undocumented, or docs contradict each other),
**performance observation** (measured, no stated guarantee), **unconfirmed anomaly** (seen once, not reproduced).

| Claim | Class | What the docs say (verbatim) | Evidence |
|---|---|---|---|
| WS-1 · TTS WebSocket `complete` arrives ~4 s after the last audio chunk | Performance observation | [Streaming](https://docs.smallest.ai/models/text-to-speech/streaming) gives timings only for the first chunk ("~100 ms", "TTFB is ~200 ms measured in-region"); no timing for `complete` | §4 |
| WS-2 · Server keeps the socket open after `complete` | Documentation mismatch | Streaming page example comment: "terminal frame; the server closes the WebSocket after this". The same page also recommends "Reuse same connection" for multiple messages, so the docs disagree with themselves | §4, 0/26 server closes + mode C |
| WS-3 · A request followed by another request on the same socket, before its `complete`, never receives `complete` | Lifecycle inconsistency | [Limits](https://docs.smallest.ai/api-reference/concurrency-and-limits): "Additional requests sent through any WebSocket while one is being processed will be rejected with an error". Observed: the follow-up was accepted with no error, and the earlier request got no terminal frame. Neither documented outcome occurred | §4, 12/12 |
| Pulse Pro returns plausible text for silence and noise (main report, Finding 2) | Correctness/safety issue | [Transcribe](https://docs.smallest.ai/api-reference/models/speech-to-text/transcribe) documents `NO_SPEECH_DETECTED` only for `language=auto` on `pulse`, and states auto is "Not available on `pulse-pro`". No Pulse Pro silence behaviour is documented, so this is not a contract violation | `results/probe_nospeech.jsonl` (21/21; Pulse control 0/9) |
| WebSocket first audio 126–167 ms vs SSE 517–625 ms | Performance observation | Streaming page quotes "~100 ms" first chunk and "~200 ms in-region"; no per-transport guarantee | §5 |
| `te`, `ta`, `kn`, `mr` accepted by Pulse pre-recorded STT | Documentation gap | Transcribe page `language` enum lists none of them | §2 |
| Pulse raw WER on Indic languages is mostly formatting | Performance observation (LLM-assisted) | None | §2 |
| 0 dB SNR raises WER by +18.6 points on paired clips | Performance observation | None | §2 |
| Kannada voice `spoorthi` once read "23" as "ಪತ್ತು ಮೂರು" | Unconfirmed anomaly | None | §3 |
| Overlapping REST TTS accepted (main report) | Documentation gap | [Limits](https://docs.smallest.ai/api-reference/concurrency-and-limits): second request gets 429; Pro model card says 10 | `results/concurrency.jsonl` |

## 1. LLM judge — what it is and how far it is trusted

Gemini `gemini-3.8-flash` is a listening assistant, never ground truth. Each clip is transcribed blind (no
expected text), then compared in a second call; replies are cached by model + prompt + audio hash
(`results/judge/`). Every number derived from it is labelled *LLM-assessed*.

| Calibration check | Result | File |
|---|---|---|
| Planted errors: 6 clips whose audio says a different value than the targets (2,540 vs 2,450; 0700 / 7000 vs 0070; negation removed) | 6/6 called wrong | `results/ext_judge_summary.json` → `planted_detection` |
| Agreement with human listening (listener R1, 58 targets of the focused trial) | 58/58 agree; 0 false alarms; 0 ambiguous | `results/ext_judge_calibration.json` |
| Known judge errors in this run | 2 correct Hindi time readings ("9:05 बजे" → "नौ बजकर पाँच मिनट") marked incomplete; speech claimed in 2 generated-silence files that Pulse correctly left empty | `results/ext_tts_judge.json`, `results/ext_asr_judge.json` |

Calibration covers value-level errors in English and Hindi. It does not validate the judge on Telugu, Tamil,
Kannada or Marathi, and it does not validate its 1–5 quality ratings; both need native human listeners.

## 2. ASR — 195 clips (192 speech + 3 no-speech controls), Pulse REST `model=pulse`

**Cohort.** Canonical manifest: `results/ext_asr_manifest_canonical.csv` (clip_id, language, condition, source,
parent_utterance_id, is_control, is_derived, included_in_wer, reference_words, speaker_id, sha256). 195 clips =
192 speech clips scored for WER + 3 no-speech controls (no language, excluded from WER). 55 clips are noise,
codec or pause variants of other utterances: they are counted as clips but not as new speakers, and their
parent is resolved to the clean root (8 kHz → A-law chains included). Counting rule: every non-derived clip
is its own root, and every derived clip points to exactly one root. That gives 145 distinct root utterances =
140 non-derived clips in this cohort (137 speech + 3 controls) + 5 roots outside this cohort. The 55 derived
clips come from 11 roots: 6 are clips in this cohort, and 5 are core-trial clips (CL-EN-01/02/03, CL-HI-01/02 =
core EN01–EN03, HI01–HI02) that are not repeated here. 69 speakers. Sources: Google SVQ, FLEURS, MUSAN (licensed; no customer audio). All 195 requests returned 200.

**Metric definitions.** Raw WER/CER: NFC, case folding, collapsed whitespace. Reported WER/CER additionally
maps Unicode digits to ASCII and removes punctuation, keeping decimal points, time colons, minus signs, ₹ and
%. No transliteration: a word in another script counts as an error. Corpus-weighted (sum of edits ÷ sum of
reference words). The **LLM-adjudicated diagnostic error rate** is NOT a WER and NOT a corrected WER: it is
the number of reference/Pulse differences that Gemini judged a real Pulse error, divided by reference words.

| Language | Clips | Ref. words | Speakers | WER | CER | *LLM-adjudicated diagnostic error rate* |
|---|---:|---:|---:|---:|---:|---:|
| English | 49 | 356 | 20 | 7.6% | 4.4% | 5.3% |
| Hindi | 56 | 563 | 17 | 21.3% | 18.8% | 2.7% |
| Telugu | 45 | 263 | 22 | 35.0% | 11.9% | 7.2% |
| Tamil | 14 | 93 | 7 | 29.0% | 15.3% | 4.3% |
| Kannada | 14 | 84 | 7 | 38.1% | 12.8% | 10.7% |
| Marathi | 14 | 102 | 7 | 16.7% | 7.3% | 3.9% |
| No-speech controls | 3 | 0 | — | — | — | Pulse output empty 3/3 |

Of 263 differences between reference and Pulse, Gemini classed 176 *equivalent* (digits vs number words,
English loanwords in Latin vs native script, word joining), 70 *Pulse error*, 17 *reference error*
(`results/ext_judge_summary.json`). Pulse errors concentrate on rare proper nouns ("Dodgers" → "Deutsche",
"వజ్రకూటం" → "వజ్రపూటం"). Telugu, Tamil, Kannada and Marathi verdicts are not checked by a native speaker.

**Conditions, paired.** Each variant is compared with Pulse's result on its own clean root utterance
(`results/ext_asr_paired.json`). This replaces the earlier unpaired comparison against a different clean pool.

| Condition (variant of the same utterance) | Pairs | Ref. words | Clean root WER | Variant WER | Δ points | Pairs worse / same / better |
|---|---:|---:|---:|---:|---:|---|
| Synthetic noise, 20 dB SNR | 8 | 59 | 20.3% | 22.0% | +1.7 | 1 / 7 / 0 |
| Synthetic noise, 10 dB SNR | 8 | 59 | 20.3% | 17.0% | −3.4 | 2 / 4 / 2 |
| Synthetic noise, 0 dB SNR | 8 | 59 | 20.3% | 39.0% | **+18.6** | 6 / 1 / 1 |
| Telephone band, 8 kHz PCM | 8 | 61 | 18.0% | 14.8% | −3.3 | 1 / 6 / 1 |
| Telephone band, 8 kHz A-law | 8 | 61 | 18.0% | 19.7% | +1.6 | 1 / 7 / 0 |
| Telephone band, 8 kHz µ-law | 8 | 61 | 18.0% | 19.7% | +1.6 | 1 / 7 / 0 |
| 1.5 s pause inserted mid-utterance | 7 | 54 | 24.1% | 24.1% | 0.0 | 2 / 4 / 1 |

Only 0 dB SNR degraded clearly in this sample. Cells of 7–8 pairs from 6 speakers in English, Hindi and Telugu
are diagnostic: they show no large regression for simulated telephone audio, not that real telephone calls are
handled well (no live carrier audio was tested).

Unpaired cells, for completeness: real-world noisy recordings 49 clips / 357 words, WER 15.7%; numbers 21 / 174,
WER 51.1% (mostly digits written as words); long utterances 4 / 90, WER 11.1%.

**Speed.** REST, all 195 clips: 799 ms median per request (p95 978 ms), RTF 0.16 median (p95 0.28); measured
while a TTS batch ran in parallel, so treat as indicative. WebSocket, 38 clips paced in real time (incl. 8 kHz
clips streamed at 8 kHz): `is_last` 38/38; final transcript 51 ms after the last audio frame was sent (median);
first non-empty partial 2.17 s after the first audio frame was sent (median).

## 3. TTS — 6 languages × 5 prompts × 2 voices (Lightning v3.1 Pro, 24 kHz)

Prompts per language: amount (₹2,450), leading-zero ID (0070), date + time (23 November, 9:05 morning),
negation (+ OTP), one conversational prompt. Voices: en kaitlyn/blake, hi meher/aviraj, te sravani/naveen,
ta tamilselvi/murugan, kn spoorthi/basava, mr ketaki/mandar. Prompts authored by me, not by native copy-editors.

| Language | Clips | *Targets correct (LLM)* | *Naturalness* | *Prosody* | *Pronunciation* |
|---|---:|---:|---:|---:|---:|
| English | 10 | 12/12 | 4.1 | 4.0 | 4.1 |
| Tamil | 10 | 12/12 | 4.1 | 3.9 | 4.3 |
| Hindi | 10 | 12/12 | 3.8 | 3.6 | 4.0 |
| Kannada | 10 | 11/12 | 3.7 | 3.7 | 4.1 |
| Marathi | 10 | 12/12 | 3.6 | 3.5 | 4.0 |
| Telugu | 10 | 12/12 | 3.6 | 3.4 | 4.0 |

All scores are *LLM-rated on a 1–5 anchored rubric, one model, one pass*. They are **not MOS** and are not
compared with human ratings yet (`results/ext_listen.html` holds a blind human rating page for all 60 clips).

**Kannada "23" — unconfirmed anomaly, not a bug.** One `spoorthi` synthesis was heard by Gemini as
"ಪತ್ತು ಮೂರು" instead of "ಇಪ್ಪತ್ತ ಮೂರು". Three fresh syntheses and the other voice read it correctly
(`results/probe_kn_date.jsonl`). No native Kannada listener has checked the original file
(`results/ext_tts/X-kn-datetime-spoorthi.wav`).

**Objective audio QC** (`results/ext_tts_qc.csv`, 66 WAVs). No near-full-scale samples. Six clips have an
internal pause > 500 ms (max 780 ms), all at the sentence break after a greeting in conversational prompts.

## 4. TTS WebSocket completion lifecycle (three separate behaviours: WS-1, WS-2, WS-3 in §0)

**Cohort of the original observation** (`results/tts_ws.jsonl` + `results/ext_latency.jsonl`, deduplicated by
request_id): 98 WebSocket runs, 98 distinct request IDs, 20:31–21:33 IST, six languages, 3–61 s of audio. It
includes 12 warm-up runs of the latency study; excluding them, 86/86 show the gap. Gap = `complete` receive time
− last audio chunk receive time, both taken with `time.perf_counter()` right after the client library returned
the frame. p50 4,025 ms, p95 4,106 ms, min 3,995 ms, max 5,127 ms. The maximum is a single run
(request `04ec0751-e789-4518-9f89-f04631b15eb6`, 20:32:11 IST); the next highest is 4,207 ms.

**Confirmation experiment** (`scripts/probe_completion.py`, 21:45–21:47 IST; sanitized frame traces without
audio payloads in `results/evidence/completion_traces/`). Five sequential short syntheses per mode, kaitlyn,
`lightning_v3.1_pro`, 24 kHz PCM. No second synthesis was started before the previous one had delivered all audio.

| Mode | What the client does | Result |
|---|---|---|
| A — one socket, wait for `complete` | Sends a `{"type":"ping"}` 500 ms after the last chunk | 5/5 gaps 4,026–4,130 ms. `pong` returned in 12–20 ms each time, then `complete` ~3.5 s later: the socket and client are responsive; the server holds `complete` |
| B — one socket, next request after 400 ms of no audio | Does not wait for `complete` | Every next request accepted, first audio 120–167 ms, no error frame. **`complete` never arrived for any request followed by another one: 12/12 across 3 runs.** Only the last request of each run got `complete`, 4,024–4,027 ms after its audio |
| C — fresh connection per request | Waits for `complete` | 5/5 gaps 4,025–4,091 ms; no server close after `complete` (client closed, no close code received) |

What the frames show, without assuming a mechanism:
- **WS-1 (timing).** `complete` follows the last audio chunk by ~4 s on every run. The docs state no timing for
  `complete`, so this is a performance observation, not a contract violation.
- **WS-2 (socket closure).** The server did not close the socket after `complete` in any run (0/26 measured in
  the focused trial, 5/5 in mode C, and modes A/B reused one socket for 5 requests). The streaming page says it
  does close. That page also recommends reusing the connection, so the docs need to choose one behaviour.
- **WS-3 (missing terminal frame).** In mode B the follow-up request was sent 400 ms after audio stopped but
  before the earlier `complete`. The server accepted it, and the earlier request never got a terminal frame.
  The limits page says a request sent while another is being processed is rejected with an error. If the first
  request was still being processed, the follow-up should have been rejected; if it was finished, its `complete`
  should have arrived. Neither happened. Whether pipelining like this is supported is not documented.

**Customer impact (request lifecycle, not playback).** Audio itself is not delayed: all of it has arrived
before the gap starts. The impact is on clients that use `complete`:
- A client that waits for `complete` before ending the bot turn or sending the next request on that socket
  defers that step by ~4 s per request.
- A client that streams several requests on one socket without waiting cannot confirm completion of any but
  the last; per-request timeouts or resource cleanup keyed on `complete` never fire.
- Workaround observed to work: treat ~400 ms without chunks as end of audio and send the next request; it is
  accepted immediately.

Illustrative acceptance target (my proposed customer criterion, not a vendor promise): one identifiable terminal
frame per request, ≤ 300 ms after its last chunk at p95, including when another request follows on the same
socket; or a documented rejection of the follow-up.

Suggested fix: document the terminal-frame and connection-reuse semantics in one place, emit a per-request end
marker (or reject early follow-ups with an error, as the limits page describes), and investigate why the terminal
frame is held ~4 s.

## 5. Latency study (isolated run, no other traffic)

English, kaitlyn, 24 kHz. Per cell: 2 warm-ups excluded, n = 5 measured, sequential, randomized transport
order per length (seed 4104). `results/ext_latency_summary.json`, raw rows in `results/ext_latency.jsonl`.

Definitions (client-observed, monotonic clock):
- **TTFA** — request sent → first decoded audio. For cold WebSocket the clock starts after the socket is open,
  so TTFA **excludes** the handshake; the handshake is a separate column.
- **Last audio** — request sent → last audio chunk received (WebSocket only; SSE ends at `done`).
- **Complete / done / total** — request sent → WebSocket `complete`, SSE `done:true`, or full REST body.
- **RTF** — total ÷ decoded audio seconds.

Median [min–max], n = 5 per cell:

| Text (audio) | Transport | TTFA ms | Handshake ms | Last audio ms | Complete / total ms | RTF |
|---|---|---|---|---|---|---|
| 63 chars (≈4 s) | WS warm | 126 [116–140] | — | 862 [788–881] | 4,887 [4,864–4,964] | 1.16 |
| | WS cold | 134 [126–144] | 129 [106–134] | 749 [729–879] | 4,800 [4,775–4,936] | 1.26 |
| | SSE | 517 [492–519] | — | — | 1,247 [1,187–1,280] | 0.29 |
| | REST | — | — | — | 1,296 [1,192–1,346] | 0.28 |
| 426 chars (≈23 s) | WS warm | 134 [130–162] | — | 3,668 [3,594–3,780] | 7,693 [7,621–7,801] | 0.34 |
| | WS cold | 140 [132–182] | 145 [109–152] | 3,749 [3,575–3,810] | 7,773 [7,606–7,873] | 0.34 |
| | SSE | 530 [481–685] | — | — | 4,221 [4,039–4,355] | 0.19 |
| | REST | — | — | — | 4,395 [4,208–4,556] | 0.19 |
| 1,042 chars (≈60 s) | WS warm | 150 [140–172] | — | 9,492 [9,391–9,831] | 13,517 [13,488–13,854] | 0.23 |
| | WS cold | 167 [154–200] | 163 [146–165] | 10,092 [9,921–10,368] | 14,118 [13,945–14,386] | 0.23 |
| | SSE | 625 [585–2,179] | — | — | 10,547 [10,165–12,992] | 0.17 |
| | REST | — | — | — | 10,453 [10,262–10,662] | 0.17 |

WebSocket RTF includes the ~4 s completion gap (§4); measured to the last chunk it is 0.16–0.20. Per-language
WebSocket TTFA (30 runs, one voice per language, 5 prompts each): p50 131 ms, p95 287 ms, min 117 ms, max 2,013 ms
(one English run). These are performance observations from one residential network: the docs' "~200 ms
in-region" figure is not a guarantee for this client, and SSE's slower first audio violates no documented contract.

## 6. Review items and what was done

| Review item | Verified? | Action taken |
|---|---|---|
| P0 Reconcile ASR counts (192 vs 195) | Totals were correct (192 speech + 3 controls; conditions also sum to 195) but the controls were hidden | Canonical manifest + denominators exported; controls shown as their own row |
| P0 Verify 98/98 | Confirmed: 98 distinct request IDs | Cohort, window, warm-ups (12), timestamp method, p50/p95/min/max and the 5.1 s run documented |
| P0 Impact of delayed completion | Original wording implied added dead air | Confirmation experiment run; impact restated as request lifecycle; new result: missing `complete` on same-socket follow-ups |
| P0 Observed vs defect | Mixed in one table before | §0 classification with the contract cited for each claim |
| P1 ASR terminology | "LLM-adjudicated error rate" could be read as WER | Renamed "LLM-adjudicated diagnostic error rate", defined as not WER, calibration and limits stated |
| P1 Denominators | Unpaired condition comparison | Reference words, speakers and derived status per cell; paired deltas against clean roots |
| P1 Latency definitions | Cold TTFA vs handshake ambiguous | Definitions written out; handshake its own column; n and ranges reported |
| P1 TTS judge limits | — | Kannada kept as unconfirmed anomaly; "not MOS" stated on the table |
| P1 Evidence for form | — | Sanitized frame traces and request IDs saved under `results/evidence/` |
| P2 Avoid extra testing | — | Only the narrow 25-request confirmation was added; no load, stress or security testing |
| Final 1 · Root-utterance count | 145 was correct but the rule was unstated (137 non-derived speech clips is a different count) | Counting rule and the 140 + 5 split written out in §2 |
| Final 2 · Pulse Pro silence classification | Reviewer right: `NO_SPEECH_DETECTED` is documented only for `language=auto` on `pulse`, "Not available on `pulse-pro`" | Reclassified from "confirmed defect" to correctness/safety issue; no contract violation claimed |
| Final 3 · Split the WebSocket behaviours | Reviewer right: one combined "confirmed defect" overstated the timing part | WS-1 performance observation, WS-2 documentation mismatch, WS-3 lifecycle inconsistency, each with the doc sentence it is checked against |

## 7. Limitations

One machine, one residential network, one evening. Judge calibration covers English/Hindi value errors only;
Indic-language verdicts and all 1–5 ratings lack native human checks. Condition cells are 7–8 pairs from six
speakers. TTS prompts were authored without native review. Telugu/Tamil/Kannada/Marathi STT codes and TTS
keepalive are undocumented and may change.

## Reproduce

```bash
python scripts/ext_asr.py prepare && python scripts/ext_asr.py rest && python scripts/ext_asr.py stream && python scripts/ext_asr.py score
python scripts/ext_manifest.py && python scripts/ext_paired.py
python scripts/ext_tts.py prepare && python scripts/ext_tts.py rest && python scripts/ext_tts.py ws && python scripts/ext_tts.py qc
python scripts/ext_judge.py tts && python scripts/ext_judge.py calibrate && python scripts/ext_judge.py asr && python scripts/ext_judge.py summary
python scripts/probe_kn_date.py
python scripts/ext_latency.py          # run alone: it is a timing study
python scripts/probe_completion.py     # focused confirmation of the completion gap
python scripts/make_ext_listen_page.py # then open results/ext_listen.html
```
