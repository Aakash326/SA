<!-- Hiring-form draft. Paste each section into the matching field. HTML comments are notes for you and are
excluded from the word count printed by scripts/build_report.py. Every number traces to results/summary.json. -->

## Scope > Area
APIs

## Why this area, and what is in and out
I build real-time voice agents, so I evaluated what a customer integrates: request validation, streaming lifecycle, latency, error semantics, limits and recovery. IN: Pulse STT (REST pulse/pulse-pro; WebSocket pulse) and Lightning v3.1 Pro TTS (REST, WebSocket, SSE), auth, negative inputs, idle/keepalive, cancel/reconnect, one controlled overlap, plus a compact ASR/TTS critical-value suite as supporting evidence. OUT: Atoms, voice cloning, pronunciation dictionaries, continuation (context_id) mode, load/stress testing, real handset/telephony audio, security probing, regional hostnames.

## Method > How you tested it: tools, how many runs, from where
16 Nov 2026, 20:14–21:47 IST, from <!-- CITY, ISP --> [city, ISP], Windows 11, Python 3.14.4, requests 2.34.2, websockets 17.4, ffmpeg 8.1.1, host api.smallest.ai (auto-routed). 356 logged calls, all sequential except one documented overlap test; STT paced under 25 RPM. Every call logged to JSONL with IST time, redacted request, status, x-request-id/session_id, input SHA-256 and monotonic client timings.

ASR: 24 licensed clips (6 English, 6 Hindi, 6 Telugu from Google SVQ; 6 Hindi-English from MUCS/OpenSLR-104), 20 distinct speakers, plus 3 no-speech controls (digital silence, two MUSAN noises). 16/24 references listener-confirmed earlier; code-switch references are dataset text. WER/CER corpus-weighted after NFC, casefold, punctuation removal. 9 paired REST/WebSocket clips, real-time paced 100 ms PCM16 frames; finals built only from is_final, session ends on is_last.

TTS: 16 prompts (money/signs, leading-zero IDs, dates/times/acronyms, negation/Hindi mix) + 4 expanded pairs, voices kaitlyn (en) and meher (hi). One human listener (me) judged all 58 targets (incl. 8 synthetic round-trip phrases) blind to an automated Pulse screen shown only after answering. Streaming: 10 WebSocket runs (5 short, 5 long), 3 SSE, 10 variant probes. 54 negative/auth cases. Timings are client-observed, not server inference. Extension (separate cohort): 195 more ASR clips (6 languages, noise, telephone codecs), 60 multilingual TTS clips, a controlled latency study, and a blind-first Gemini judge validated on 6/6 planted errors and 58/58 human marks. Limits: one machine, network and evening; small cells; one human listener; Gemini scores are LLM-assessed, not MOS; no load, live-telephony or handset tests.

## Finding 1 > Title
WebSocket TTS completion lifecycle differs from documented expectations

## Finding 1 > Area / Severity
APIs / Medium

## Finding 1 > Expected
A client can tell when each ordinary request is finished. Streaming docs: "complete" is the "terminal frame; the server closes the WebSocket after this". Limits page: a request sent "while one is being processed will be rejected with an error". No timing is documented for "complete".

## Finding 1 > Observed
Three separate behaviours. (1) Timing (performance observation): across 98 requests (98 request IDs, six languages, 3–61 s audio), "complete" followed the final chunk by p50 4,025 ms, p95 4,106 ms; ping/pong answered in 12–20 ms during the wait. (2) Documentation mismatch: the server never closed the socket after "complete" (0/26; reuse worked). (3) Lifecycle inconsistency: a follow-up sent on the same socket 400 ms after audio stopped was accepted with no error, and the earlier request never received "complete": 12/12 across 3 runs. Neither documented outcome occurred.

## Finding 1 > Evidence
wss://api.smallest.ai/waves/v1/tts/live, {"text":"Your reference ID is 0070.","voice_id":"kaitlyn","model":"lightning_v3.1_pro","language":"en","sample_rate":24000,"output_format":"pcm"}. First chunk 122 ms, last chunk 1,183 ms, complete 5,207 ms (ccb4720a-03ce-4f2f-8e48-fe83994f3c47). No complete: 8a8827a2-c503-4508-bec4-ffaacffdd96d, 4a28a44d-41d7-4046-9302-38b392e67f97. Monotonic receive timestamps; 20:31–21:47 IST.

## Finding 1 > Customer impact, against an SLO
Not a playback delay: audio has fully arrived before the gap. Clients that wait for "complete" to end the turn or release request state wait ~4 s; clients that send the next request early never get per-request confirmation, so timeouts and cleanup misfire. Proposed customer criterion (not a vendor promise): one terminal frame per request, ≤ 300 ms after its last chunk at p95. Workaround: treat 400 ms without chunks as end of audio.

## Finding 2 > Title
Pulse Pro returns confident text for silent or noise-only audio

## Finding 2 > Area / Severity
APIs / Medium

## Finding 2 > Expected
Customer expectation, not a documented Pulse Pro contract (NO_SPEECH_DETECTED is documented only for language=auto on pulse): no speech, no transcript. Pulse returns "" on the same files.

## Finding 2 > Observed
pulse-pro, language=en: 21/21 no-speech requests returned status 200 with plausible text and no flag. Digital silence (all samples 0; 1, 4, 10 s) → "Four" or "Go ahead."; −60 dBFS white noise → "I'm sorry."; MUSAN noise → "I'm sorry.", "Applause". Deterministic per file (3/3). Control: pulse 0/9 non-empty.

## Finding 2 > Evidence
POST /waves/v1/stt/?model=pulse-pro&language=en, 4 s 16 kHz mono PCM16 WAV of zeros → {"status":"success","transcription":"Four","language":"en",…}. request_ids ac81c039-71cf-4cb8-95e8-3db30d0b476c, af58b428-befc-480b-9d35-31bd01f91a9c, e55d0341-2450-42cc-80b1-d6a7828e7901. 20:18–20:46 IST.

## Finding 2 > Customer impact, against an SLO
Silent stretches are common in recordings (hold, one-sided stereo channels, voicemail). "Four" or "Go ahead." becomes a false customer utterance in analytics, compliance records or IVR choices. Proposed criterion: 0 non-empty transcripts on a 20-file silence/noise set. Workaround: client-side VAD.

## Finding 3 > Title
Pulse WebSocket finals differ from REST on identical audio (wrong year; duplicated words after finalize)

## Finding 3 > Area / Severity
APIs / Medium

## Finding 3 > Expected
The same model on the same audio should yield the same critical values over REST and WebSocket; finalize should split a segment without repeating words.

## Finding 3 > Observed
(a) Clip EN05, reference "Who was the leader of Switzerland in 1499?": REST 4/4 "1499"; WebSocket language=en 8/8 "1999", across 100 ms, 128 ms (documented 4096 B), 20 ms and unpaced chunking and itn_normalize=true. (b) finalize at 50% on CS03 returned "arguments के साथ के साथ main" 3/3; without finalize 0/3; three other clips 0/3. Seven more paired number clips showed no general WebSocket weakness, so (a) is one reproducible utterance, not a rate.

## Finding 3 > Evidence
wss://…/stt/live?model=pulse&language=en&encoding=linear16&sample_rate=16000, PCM16 paced in real time, then close_stream; is_final/is_last both true. Sessions 604ed2db-b4b1-46be-a054-d021165d71cc, b7d79747-0ce0-4d1d-9fdd-503ced191f1a; finalize sessions logged. 20:17–20:45 IST.

## Finding 3 > Customer impact, against an SLO
Streaming is the voice-agent path; a changed year, amount or repeated phrase reaches the LLM as fact. Proposed target: REST/WebSocket critical-slot agreement 100% on a paired regression set; 0 duplicated tokens at finalize boundaries.

## Finding 4 > Title
Documented contract differs from observed behaviour in several places

## Finding 4 > Area / Severity
APIs / Low

## Finding 4 > Expected / Observed
(1) Limits page: second concurrent TTS gets 429; observed overlapping REST TTS 200 in 3/3. (2) Synthesize page: mismatched voice/language returns 400; kaitlyn+hi and meher+en return 200. (3) /lightning-v3.1-pro/get_voices returns 200 with invalid or no key. (4) Error bodies use six shapes, including HTML for malformed JSON. (5) Socket closes: STT normal end 1005 (46/46), idle timeouts 1006 on STT and TTS; best-practices reconnect logic reconnects on any non-1000, so clients reconnect after every normal session. (6) TTS WebSocket ping/pong, ?timeout and 60 s idle timeout work but are undocumented. (7) STT language omitted → "Language 'multi' has not been enabled in this region".

## Finding 4 > Customer impact
Clients coded to the docs mishandle retries, reconnects and errors. Target: docs and responses agree for every case.

## What is done well
Auth: 401 on all 10 bad-credential REST/WebSocket cases, no key echoed. Validation: 23/24 invalid HTTP inputs rejected with 400, most naming the field and allowed values. REST STT 27/27 success, median 688 ms. STT streaming matches docs: is_last on 47/47 sessions, final 51 ms after last audio (median); finalize, ping and timeout as documented. TTS WebSocket first audio 131 ms median across 6 languages (n=30), no simulated underrun at 200 ms buffer; cancel and reconnect recovered 2/2. ASR WER: English 10.3% (Pulse Pro 7.7%), Hindi 15.6%, Telugu 40.0% (CER 17.1%). Extension: LLM-adjudicated diagnostic error rate (not WER) ≤ 11% in six languages; simulated 8 kHz/A-law/µ-law within ±5 points of each clip's clean result. TTS: 58/58 targets correct by human listening (leading zeros, signs, decimals, dates, negation). With meher and language=hi, numbers in English sentences are spoken in Hindi; number_pronunciation_language=en fixes it (4/4, listened).

## Top fixes > Fix 1 and Why it comes first
Define and implement one per-request terminal frame on the TTS WebSocket: sent right after each request's final chunk, also when another request follows (or reject early follow-ups as the limits page says), and align the docs on socket closure. Why first: it affects every streaming integration's turn handling. Acceptance: one terminal frame per request_id, p95 ≤ 300 ms after the last chunk, over 50 single and pipelined runs.

## Top fixes > Fix 2 and Why it comes first
Give Pulse Pro no-speech handling: empty transcript or an explicit no-speech flag for silence/noise, as Pulse does. Why second: deterministic false text with status 200 corrupts records silently; a VAD workaround exists. Acceptance: 0/20 non-empty on a silence/noise set; Pulse Pro English WER unchanged.

## Top fixes > Fix 3 and Why it comes first
Run a REST-vs-WebSocket parity suite (critical numbers, finalize boundaries) in CI, and align docs on 429, voice/language validation, error schema and close codes (send 1000 on normal end). Why third: lower individual severity but affects every integration. Acceptance: EN05 and CS03 pass; documented and observed statuses match for all 54 cases.

## Time spent, in hours
<!-- actual hours incl. prep, testing and writing --> [X]

## Links
<!-- optional, sanitised repo only; no key --> [optional]

## Private: security concern
<!-- Leave empty. The unauthenticated voices list returns only the public catalogue; it is reported as a contract mismatch, not a security issue. -->
