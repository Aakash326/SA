# Documented contract used as the test oracle

Read on 16 November 2026 (IST). Field names and values are literals from the pages; descriptions are paraphrased.
Every "Expected" column in the test logs points back to a line in this file.

## Authentication — https://docs.smallest.ai/api-reference/authentication
- `Authorization: Bearer <key>`. 401 = missing/invalid/expired key; 403 = key lacks access; 429 = rate limit.
- Literal 401/429 bodies are not documented.

## Pulse pre-recorded STT — https://docs.smallest.ai/api-reference/models/speech-to-text/transcribe
- `POST https://api.smallest.ai/waves/v1/stt/?model=<pulse|pulse-pro>&language=<code>`; body raw bytes
  (`application/octet-stream`) or `application/json` `{"url": ...}`.
- `model` required (missing/invalid → 400). `pulse-pro` accepts only `en`.
- `language` enum: `en, hi, de, es, ru, it, fr, nl, pt, zh, ja, ko, multi-eu, multi-asian, multi-indic, auto`.
  No default documented ("Always pass `language`"). `te` is **not** in the enum.
- Boolean query params are lowercase strings only.
- 200 body: `status`, `transcription`, `words`, `utterances` (Pulse), `metadata`; `request_id` is documented for
  Pulse Pro only.
- Error body fields: `error`, `status`, `message`, `error_code`, `code`, `request_id`, `errors[]`, …
  `code` values include `AudioDecodeError`, `NoAudio`, `AudioTooLong`. `NO_SPEECH_DETECTED` (422) is documented only for
  `language=auto` on `pulse` ("Detection fails with an error instead of guessing"); auto is "Not available on `pulse-pro`".
  No silence behaviour is documented for Pulse Pro (re-checked 16 Nov 2026).
- 429: "RPM cap exceeded (Standard plan default 25/min per model)"; retry with exponential backoff.

## Pulse real-time STT — https://docs.smallest.ai/api-reference/models/speech-to-text/speech-to-text
- `wss://api.smallest.ai/waves/v1/stt/live`; `model` default `pulse` (`pulse-pro` rejected with 400 at handshake).
- `encoding` default `linear16`; `sample_rate` enum 8000/16000/22050/24000/44100/48000; `itn_normalize` default `false`.
- Client: binary audio; `{"type":"finalize"}` → one `is_final:true` + `from_finalize:true`, socket stays open, no
  `is_last`; `{"type":"close_stream"}` → `is_final:true` + `is_last:true`, then server closes.
  `{"type":"ping"}` → `{"type":"pong"}`.
- Server: `type:"transcription"` with `transcript`/`transcription`, `is_final`, `is_last`, `session_id`, …;
  `type:"error"` with `error_code`, `message`, `retryable`.
- Best practices: 4096-byte chunks (1024–8192), send every 50–100 ms.
- Keep-alive page: `timeout` query param in seconds; timeout message `{"status":"error","message":"Connection timed out after N seconds of inactivity"}`.

## Lightning TTS REST — https://docs.smallest.ai/api-reference/models/text-to-speech/synthesize-speech
- `POST https://api.smallest.ai/waves/v1/tts`, JSON body; model in body.
- `model`: `lightning_v3.1`, `lightning_v3.1_pro`, `lightning_v3.1_pro_10_26`.
- `sample_rate` enum 8000/16000/24000/44100 (default 44100); `speed` 0.5–2.0; `output_format` enum
  `mp3, pcm, wav, ulaw, alaw` (default `pcm`); `text` max 8000 chars, whitespace-only rejected.
- Errors documented: 400/401/500, body `{error?, message?}`; example 400
  `Voice '<id>' is not available on the lightning_v3.1_pro model`.

## Lightning TTS streaming — https://docs.smallest.ai/models/text-to-speech/streaming
- WebSocket `wss://api.smallest.ai/waves/v1/tts/live`: frames `status:"chunk"` with `data.audio` (base64 PCM),
  terminal `status:"complete"`. Example comment: "terminal frame; the server closes the WebSocket after this". The same
  page's comparison table says "Multiple messages | Reuse same connection". No timing is given for `complete`.
- Limits page: "Additional requests sent through any WebSocket while one is being processed will be rejected with an error".
- SSE `POST /waves/v1/tts/live` with `Accept: text/event-stream`: top-level `audio`, `done:false`; terminal `done:true`.
- Latency text: "First chunk arrives in ~100ms" and "TTFB is ~200 ms measured in-region"; 500–800 ms from a distant laptop.
- Not documented for TTS WebSocket: query parameters, `timeout`, ping/pong, idle timeout, close codes, error frame.

## Limits — https://docs.smallest.ai/api-reference/concurrency-and-limits
- "Only 1 Text-to-Speech request can be actively processed at a time per account."
- Up to 5 WebSocket connections; one concurrent request across them; a second HTTP request gets 429.
- "all models share the same concurrency limit."
- Regions: `api.india.smallest.ai` (Mumbai), `api.us.smallest.ai` (Oregon); `api.smallest.ai` auto-routes.

## Documented contradictions (each settled by a test where cheap)

| ID | Topic | Source A | Source B | Test |
|---|---|---|---|---|
| C1 | TTS concurrency | Limits page: 1 per account | Pro model card: "Concurrency (Standard Plan) 10" | R01 |
| C2 | Default model when omitted | Synthesize page: picked from voice | Pro card FAQ: defaults to standard v3.1 | D02 |
| C3 | Voice/language mismatch | Synthesize page: returns 400 | Pro card: API does not reject | E04 |
| C4 | First chunk latency | "~100ms" | "~200 ms in-region" (same page) | S01 |
| C5 | `output_format` default vs `Accept: audio/wav` | `output_format` default `pcm` | `Accept` default `audio/wav` | D03 |
| C6 | Voices endpoint path | `/lightning-v3.1/get_voices` | `/lightning-v3.1-pro/get_voices` | D04 |
| C7 | STT language set | Reference enum lacks `te` | TTS lists `te`; Pulse marketed multilingual | E07 / A01 |
| C8 | STT concurrency scope | "all models share the same concurrency limit" | 429 text scoped to TTS | R01 (tts+stt) |
