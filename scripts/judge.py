"""Gemini as an independent listening assistant. Never the system under test, never ground truth.

Adapted from the Gnani evaluation (gnani/gemini_judge.py):
- Blind first: audio is transcribed WITHOUT the expected text; comparison happens in a second call.
- Every reply is cached under results/judge/<task>/<id>__<fingerprint>.json, keyed by model + prompt + audio bytes,
  so reruns cost nothing and any change to prompt/audio is a cache miss.
- Calibration (ext_judge.py calibrate) measures misses on planted errors and agreement with human marks before
  any judge number is reported. Every judge-derived number is labelled "LLM-assessed".
"""
import hashlib
import json
import os
import re
import time

from common import RESULTS, ROOT, load_env

load_env()
MODEL = os.environ.get('GEMINI_JUDGE_MODEL', 'gemini-3.8-flash')
CACHE = RESULTS / 'judge'
LANG_NAMES = {'en': 'English (Indian or international accent)', 'hi': 'Hindi (may include English words)',
              'te': 'Telugu', 'ta': 'Tamil', 'kn': 'Kannada', 'mr': 'Marathi', 'en-IN': 'Indian English',
              'hi-IN': 'Hindi', 'te-IN': 'Telugu', 'ta-IN': 'Tamil', 'kn-IN': 'Kannada', 'mr-IN': 'Marathi',
              '': 'the language(s) heard', 'none': 'the language(s) heard'}
_client = None


def client():
    global _client
    if _client is None:
        from google import genai
        key = os.environ.get('GEMINI_API_KEY', '').strip()
        if not key:
            raise RuntimeError('GEMINI_API_KEY missing in .env')
        _client = genai.Client(api_key=key)
    return _client


def ask(task, item_id, audio_path, prompt):
    from google.genai import types
    path = audio_path if os.path.isabs(str(audio_path)) else ROOT / audio_path
    audio = open(path, 'rb').read()
    fp = hashlib.sha256(MODEL.encode() + b'\0' + prompt.encode('utf-8') + b'\0' + audio).hexdigest()[:16]
    cache = CACHE / task / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', item_id)}__{fp}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf-8'))
    last, data, resp, t0 = None, None, None, time.perf_counter()
    for attempt in range(1, 5):
        t0 = time.perf_counter()
        try:
            resp = client().models.generate_content(
                model=MODEL, contents=[types.Part.from_bytes(data=audio, mime_type='audio/wav'), prompt],
                config=types.GenerateContentConfig(temperature=0, response_mime_type='application/json'))
            data = json.loads(resp.text or '')
            break
        except Exception as error:  # rate limit, transient error, malformed JSON
            last = error
            time.sleep(3 * attempt)
    if data is None:
        raise RuntimeError(f'{task}/{item_id}: {last}')
    usage = getattr(resp, 'usage_metadata', None)
    out = dict(task=task, id=item_id, model=MODEL, fingerprint=fp, audio=str(audio_path), audio_sha256=hashlib.sha256(audio).hexdigest(),
               latency_ms=round((time.perf_counter() - t0) * 1000), reply=data,
               tokens=dict(prompt=getattr(usage, 'prompt_token_count', None), output=getattr(usage, 'candidates_token_count', None)) if usage else None)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


# ------------------------------------------------------------------ ASR side
def asr_blind(item_id, audio_path, language):
    lang = LANG_NAMES.get(language, language)
    prompt = (f'You are a careful human transcriber. Transcribe exactly what is spoken in this audio ({lang}). Write every '
              'word actually said, including repetitions; do not correct grammar or guess unclear words. Write Hindi and '
              'Marathi in Devanagari, Telugu, Tamil and Kannada in their own scripts, English words in Latin letters, '
              'numbers as digits. If no speech is audible return an empty transcript. Reply with JSON only: '
              '{"transcript": str, "language": str, "no_speech": bool, "unclear": [str]}.')
    return ask('asr_blind', item_id, audio_path, prompt)


def asr_adjudicate(item_id, audio_path, language, reference, hypothesis, blind):
    """Per-difference verdict between the dataset reference and Pulse's hypothesis."""
    lang = LANG_NAMES.get(language, language)
    prompt = (f'You are adjudicating a speech-recognition test ({lang}). Listen to the audio carefully.\n'
              f'Reference transcript (from the dataset): {reference}\n'
              f'System transcript (under test): {hypothesis}\n'
              f'An independent blind transcript: {blind}\n'
              'List every place where the reference and the system transcript differ. For each difference decide from '
              'what is AUDIBLE: "system_error" (system wrote something not spoken), "reference_error" (reference does not '
              'match the audio and the system is right), "equivalent" (same spoken content: spelling variant, script '
              'choice for an English loanword, digits vs number words, word joining/splitting, punctuation), or '
              '"unclear". Then give your own best transcript. Reply with JSON only: {"differences": [{"reference": str, '
              '"system": str, "verdict": "system_error"|"reference_error"|"equivalent"|"unclear"}], '
              '"reference_matches_audio": bool, "best_transcript": str, "confidence": "high"|"medium"|"low"}.')
    return ask('asr_adjudicate', item_id, audio_path, prompt)


# ------------------------------------------------------------------ TTS side
def tts_blind(item_id, audio_path, language):
    lang = LANG_NAMES.get(language, language)
    prompt = (f'This is synthetic speech ({lang}). Write down exactly what you hear, word for word, as a listener would. '
              "Write numbers the way they are SPOKEN (e.g. 'two thousand four hundred fifty', 'zero zero seven zero'), spell "
              "letter-by-letter acronyms with spaces (e.g. 'O T P'), keep native scripts for Indian-language words and note "
              'which language each number was spoken in. If a word is unclear write your best guess in [brackets]. '
              'Reply with JSON only: {"heard": str, "number_language": str, "unclear": [str]}.')
    return ask('tts_blind', item_id, audio_path, prompt)


def tts_judge(item_id, audio_path, language, text, targets, blind):
    lang = LANG_NAMES.get(language, language)
    prompt = (f'You are a strict listening judge for a text-to-speech test ({lang}). Listen to the audio again.\n'
              f'Text sent to the TTS system: {text}\nYour earlier blind transcription: {blind}\n'
              f'Targets to check (fixed before the audio existed): {json.dumps(targets, ensure_ascii=False)}\n'
              "For each target decide from what is AUDIBLE only: 'correct' if what is spoken has the same value/meaning "
              "(in any language or reading convention), 'wrong' if a different value or word is spoken, a sign, a 'not' or "
              "a leading zero is lost, or the item is skipped; 'ambiguous' if you cannot tell clearly. Then rate, using these "
              'anchors: 1 severe problems, 2 substantial problems, 3 noticeable issues but understandable, 4 mostly natural '
              'with minor issues, 5 natural and clear. naturalness = human-like voice quality; prosody = stress, rhythm, '
              'pauses and intonation suitable for the sentence (e.g. a question rises); pronunciation = words in the '
              'intended language pronounced like a native speaker would. List audible artifacts (clicks, glitches, '
              'truncation, wrong language, robotic segments, long silences). Reply with JSON only: '
              '{"targets": [{"id": str, "result": "correct"|"wrong"|"ambiguous", "heard": str}], "content_complete": bool, '
              '"spoken_language": str, "naturalness_1to5": int, "prosody_1to5": int, "pronunciation_1to5": int, '
              '"artifacts": [str], "comment": str}.')
    return ask('tts_judge', item_id, audio_path, prompt)
