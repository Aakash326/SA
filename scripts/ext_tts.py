"""Stage 9 X-TTS-1/3/4: multilingual Lightning v3.1 Pro prompts, planted-error controls, REST + WebSocket timing, QC.

usage: python scripts/ext_tts.py prepare   # templates/ext_tts_prompts.csv
       python scripts/ext_tts.py rest      # REST synthesis, every prompt x voice (resumable) -> results/ext_tts/
       python scripts/ext_tts.py ws        # WebSocket TTFA, first voice per language, every prompt (resumable)
       python scripts/ext_tts.py qc        # objective audio checks -> results/ext_tts_qc.csv

Every prompt uses the same four critical targets per language (amount 2,450 rupees; ID 0070; date 23 November
+ time 9:05 morning; negation + OTP), plus one conversational prompt for naturalness/prosody.
PLANTED rows deliberately send a different value than their targets; the judge must call them wrong.
"""
import asyncio
import csv
import json
import math
import struct
import sys
import time

import requests

from common import HTTP, RESULTS, ROOT, Clock, auth, body_excerpt, headers_of, log, read_jsonl, sha256, wav_info
from tts_ws import ws_run

MANIFEST = ROOT / 'templates' / 'ext_tts_prompts.csv'
OUT = RESULTS / 'ext_tts'
VOICES = {'en': ('kaitlyn', 'blake'), 'hi': ('meher', 'aviraj'), 'te': ('sravani', 'naveen'),
          'ta': ('tamilselvi', 'murugan'), 'kn': ('spoorthi', 'basava'), 'mr': ('ketaki', 'mandar')}
TEXT = {
    'en': ['Your account has been credited with ₹2,450.', 'Your reference number is 0070.',
           'Your meeting is on 23 November at 9:05 AM.', 'Please do not share your OTP with anyone.',
           'Hello! How can I help you today? If you need any information about your account, please feel free to ask.'],
    'hi': ['आपके खाते में ₹2,450 जमा हो गए हैं।', 'आपका रेफरेंस नंबर 0070 है।', 'आपकी मीटिंग 23 नवंबर को सुबह 9:05 बजे है।',
           'कृपया अपना OTP किसी के साथ साझा न करें।',
           'नमस्ते! मैं आपकी कैसे मदद कर सकती हूँ? अगर आपको अपने खाते के बारे में कोई जानकारी चाहिए, तो बेझिझक पूछिए।'],
    'te': ['మీ ఖాతాలో ₹2,450 జమ అయ్యాయి.', 'మీ రిఫరెన్స్ నంబర్ 0070.', 'మీ మీటింగ్ నవంబర్ 23న ఉదయం 9:05 గంటలకు ఉంది.',
           'దయచేసి మీ OTP ని ఎవరితోనూ పంచుకోవద్దు.',
           'నమస్కారం! నేను మీకు ఎలా సహాయం చేయగలను? మీ ఖాతా గురించి ఏదైనా సమాచారం కావాలంటే, దయచేసి అడగండి.'],
    'ta': ['உங்கள் கணக்கில் ₹2,450 வரவு வைக்கப்பட்டுள்ளது.', 'உங்கள் குறிப்பு எண் 0070.',
           'உங்கள் சந்திப்பு நவம்பர் 23 அன்று காலை 9:05 மணிக்கு உள்ளது.', 'தயவுசெய்து உங்கள் OTP-ஐ யாருடனும் பகிர வேண்டாம்.',
           'வணக்கம்! நான் உங்களுக்கு எப்படி உதவ முடியும்? உங்கள் கணக்கு பற்றி ஏதேனும் தகவல் தேவைப்பட்டால், தயங்காமல் கேளுங்கள்.'],
    'kn': ['ನಿಮ್ಮ ಖಾತೆಗೆ ₹2,450 ಜಮೆಯಾಗಿದೆ.', 'ನಿಮ್ಮ ರೆಫರೆನ್ಸ್ ಸಂಖ್ಯೆ 0070.', 'ನಿಮ್ಮ ಸಭೆ ನವೆಂಬರ್ 23 ರಂದು ಬೆಳಿಗ್ಗೆ 9:05 ಕ್ಕೆ ಇದೆ.',
           'ದಯವಿಟ್ಟು ನಿಮ್ಮ OTP ಅನ್ನು ಯಾರೊಂದಿಗೂ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ.',
           'ನಮಸ್ಕಾರ! ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು? ನಿಮ್ಮ ಖಾತೆಯ ಬಗ್ಗೆ ಯಾವುದೇ ಮಾಹಿತಿ ಬೇಕಿದ್ದರೆ, ದಯವಿಟ್ಟು ಕೇಳಿ.'],
    'mr': ['तुमच्या खात्यात ₹2,450 जमा झाले आहेत.', 'तुमचा संदर्भ क्रमांक 0070 आहे.', 'तुमची मीटिंग 23 नोव्हेंबरला सकाळी 9:05 वाजता आहे.',
           'कृपया तुमचा OTP कोणालाही सांगू नका.',
           'नमस्कार! मी तुम्हाला कशी मदत करू शकते? तुमच्या खात्याबद्दल काही माहिती हवी असल्यास, नक्की विचारा.'],
}
KINDS = ['amount', 'id', 'datetime', 'negation', 'natural']
TARGETS = {
    'amount': [dict(id='amount', written='₹2,450', must_hear='two thousand four hundred fifty rupees (any language)', critical=True)],
    'id': [dict(id='id', written='0070', must_hear='zero zero seven zero, digit by digit, leading zeros kept (any language)', critical=True)],
    'datetime': [dict(id='date', written='23 November', must_hear='twenty-third (of) November', critical=True),
                 dict(id='time', written='9:05 morning', must_hear='nine oh five / five past nine, morning', critical=True)],
    'negation': [dict(id='negation', written='do not', must_hear='a clear negative instruction (do not / न / వద్దు / வேண்டாம் / ಬೇಡಿ / नका)', critical=True),
                 dict(id='otp', written='OTP', must_hear='O T P', critical=False)],
    'natural': [dict(id='question', written='How can I help you?', must_hear='the question is spoken, as a question', critical=False)],
}
# Planted controls: text differs from the targets on purpose (2,540 instead of 2,450; negation removed).
PLANTED = {'en': ('Your account has been credited with ₹2,540.', 'amount'), 'hi': ('आपके खाते में ₹2,540 जमा हो गए हैं।', 'amount'),
           'te': ('మీ రిఫరెన్స్ నంబర్ 0700.', 'id'), 'ta': ('உங்கள் கணக்கில் ₹2,540 வரவு வைக்கப்பட்டுள்ளது.', 'amount'),
           'kn': ('ದಯವಿಟ್ಟು ನಿಮ್ಮ OTP ಅನ್ನು ಎಲ್ಲರೊಂದಿಗೆ ಹಂಚಿಕೊಳ್ಳಿ.', 'negation'), 'mr': ('तुमचा संदर्भ क्रमांक 7000 आहे.', 'id')}


def prepare():
    rows = []
    for lang, texts in TEXT.items():
        for kind, text in zip(KINDS, texts):
            for voice in VOICES[lang]:
                rows.append(dict(case_id=f'X-{lang}-{kind}-{voice}', language=lang, kind=kind, voice_id=voice, text=text,
                                 planted='false', targets_json=json.dumps(TARGETS[kind], ensure_ascii=False)))
        text, kind = PLANTED[lang]
        rows.append(dict(case_id=f'P-{lang}-{kind}', language=lang, kind=kind, voice_id=VOICES[lang][0], text=text,
                         planted='true', targets_json=json.dumps(TARGETS[kind], ensure_ascii=False)))
    with open(MANIFEST, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(len(rows), 'rows;', sum(r['planted'] == 'true' for r in rows), 'planted')


def prompts():
    return list(csv.DictReader(open(MANIFEST, encoding='utf-8-sig')))


def rest():
    OUT.mkdir(parents=True, exist_ok=True)
    done = {r['case_id'] for r in read_jsonl('ext_tts_rest') if r.get('wav')}
    for p in prompts():
        if p['case_id'] in done:
            continue
        payload = {'text': p['text'], 'voice_id': p['voice_id'], 'model': 'lightning_v3.1_pro', 'language': p['language'],
                   'sample_rate': 24000, 'output_format': 'wav'}
        clock = Clock()
        r = requests.post(f'{HTTP}/tts', headers={**auth(), 'Content-Type': 'application/json'}, json=payload, timeout=90)
        elapsed = clock.ms()
        info = wav_info(r.content) if r.ok else None
        if info:
            (OUT / f"{p['case_id']}.wav").write_bytes(r.content)
        log('ext_tts_rest', dict(test='X-TTS', case_id=p['case_id'], language=p['language'], kind=p['kind'], voice=p['voice_id'],
                                 planted=p['planted'], request=payload, chars=len(p['text']), status=r.status_code, elapsed_ms=elapsed,
                                 headers=headers_of(r), wav=info, rtf=round(elapsed / 1000 / info['duration_s'], 4) if info else None,
                                 output_sha256=sha256(r.content) if info else None, body=None if info else body_excerpt(r)))
        print(p['case_id'], r.status_code, elapsed, 'ms', info and info['duration_s'], 's')
        time.sleep(0.4)


def ws():
    done = {r['request'].get('text') + '|' + r['request'].get('voice_id') for r in read_jsonl('tts_ws') if r['test'] == 'X-TTFA'}
    for p in prompts():
        if p['planted'] == 'true' or p['voice_id'] != VOICES[p['language']][0]:
            continue
        if p['text'] + '|' + p['voice_id'] in done:
            continue
        row = asyncio.run(ws_run(p['text'], p['voice_id'], p['language'], tag='X-TTFA', after_complete_s=0.5))
        print(p['case_id'], 'TTFA', row.get('first_audio_ms'), 'audio', row.get('audio_s'), 's complete', row.get('complete_ms'))
        time.sleep(1.0)


def qc():
    rows = []
    for path in sorted(OUT.glob('*.wav')):
        data = path.read_bytes()
        info = wav_info(data)
        start = data.find(b'data') + 8
        pcm = data[start:start + info['data_bytes']]
        samples = struct.unpack(f'<{len(pcm) // 2}h', pcm[:len(pcm) // 2 * 2])
        frame = int(info['sample_rate'] * 0.02)
        rms = [math.sqrt(sum(s * s for s in samples[i:i + frame]) / frame) for i in range(0, len(samples) - frame, frame)]
        db = [20 * math.log10(v / 32768) if v else -120 for v in rms]
        voiced = [i for i, v in enumerate(db) if v > -50]
        lead = (voiced[0] * 20) if voiced else None
        trail = ((len(db) - 1 - voiced[-1]) * 20) if voiced else None
        gaps, run = [], 0
        for v in db[voiced[0]:voiced[-1] + 1] if voiced else []:
            run = run + 20 if v <= -50 else 0
            if run == 520:
                gaps.append(run)
        longest = 0
        run = 0
        for v in db[voiced[0]:voiced[-1] + 1] if voiced else []:
            run = run + 20 if v <= -50 else 0
            longest = max(longest, run)
        rows.append(dict(case_id=path.stem, duration_s=info['duration_s'], sample_rate=info['sample_rate'],
                         rms_dbfs=round(20 * math.log10(math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768), 1),
                         peak=max(abs(s) for s in samples), near_full_scale=sum(1 for s in samples if abs(s) >= 32760),
                         leading_silence_ms=lead, trailing_silence_ms=trail, internal_gaps_over_500ms=len(gaps),
                         longest_internal_gap_ms=longest))
    with open(RESULTS / 'ext_tts_qc.csv', 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(len(rows), 'files; near-full-scale files', sum(1 for r in rows if r['near_full_scale']),
          '; files with internal gap >500 ms', sum(1 for r in rows if r['internal_gaps_over_500ms']),
          '; longest gap', max(r['longest_internal_gap_ms'] for r in rows), 'ms')


if __name__ == '__main__':
    {'prepare': prepare, 'rest': rest, 'ws': ws, 'qc': qc}[sys.argv[1]]()
