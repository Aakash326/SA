"""Stage 6 (E01-E07): validation and error contract, one request per case.

usage: python scripts/negative.py [--only E04,E06]
Each row records status, the body excerpt, whether the body is JSON, which documented error fields are
present, and whether any part of the submitted key appears in the response.
"""
import argparse
import asyncio
import json
import time
import urllib.parse

import requests
import websockets

from common import HTTP, ROOT, WSS, Clock, api_key, auth, body_excerpt, headers_of, log, wav_info

KEY = api_key()
BAD_KEY = 'sk_' + '0' * 32
TTS_OK = {'text': 'Validation check.', 'voice_id': 'kaitlyn', 'model': 'lightning_v3.1_pro', 'language': 'en',
          'sample_rate': 24000, 'output_format': 'wav'}
CLIP = open(__file__.replace('scripts\\negative.py', 'clips\\EN01.wav').replace('scripts/negative.py', 'clips/EN01.wav'), 'rb').read()


def leaks(text):
    return any(part and part in text for part in (KEY, KEY[3:19], BAD_KEY))


def http(case, note, expected, method, path, *, headers=None, **kwargs):
    clock = Clock()
    try:
        r = requests.request(method, f'{HTTP}{path}', headers=headers if headers is not None else auth(), timeout=90, **kwargs)
    except requests.RequestException as error:  # e.g. server closes the connection before the upload finishes
        row = log('negative', dict(test=case, note=note, expected=expected, method=method, url=f'{HTTP}{path}',
                                   params=kwargs.get('params'), request=kwargs.get('json') or
                                   (f"<{len(kwargs['data'])} bytes>" if 'data' in kwargs else None),
                                   status=None, transport_error=repr(error)[:300], elapsed_ms=clock.ms()))
        print(f'{case:4} {note:58} -> transport error {repr(error)[:120]}')
        time.sleep(1.0)
        return row
    text = body_excerpt(r, 800)
    try:
        body = r.json()
    except ValueError:
        body = None
    fields = sorted(body) if isinstance(body, dict) else None
    row = log('negative', dict(test=case, note=note, expected=expected, method=method, url=r.url,
                               request=kwargs.get('json') or (f"<{len(kwargs['data'])} bytes>" if 'data' in kwargs else None),
                               auth_sent='none' if headers is not None and 'Authorization' not in headers else
                               ('invalid' if headers is not None else 'valid'),
                               status=r.status_code, elapsed_ms=clock.ms(), headers=headers_of(r), json_body=body is not None,
                               body_fields=fields, body=text, audio=wav_info(r.content) if r.ok else None,
                               key_material_in_response=leaks(r.text if body is not None else text)))
    print(f'{case:4} {note:58} -> {r.status_code} {text[:150]}')
    time.sleep(1.0)
    return row


async def ws(case, note, expected, url, *, headers=None, send=(), wait_s=8):
    clock = Clock()
    row = dict(test=case, note=note, expected=expected, url=url, sent=[s if isinstance(s, str) else f'<{len(s)} bytes>' for s in send])
    try:
        conn = await websockets.connect(url, additional_headers=headers if headers is not None else auth(), open_timeout=20)
    except Exception as error:
        response = getattr(error, 'response', None)
        body = (response.body or b'').decode('utf-8', 'replace')[:500] if response is not None else None
        row.update(handshake='rejected', handshake_status=getattr(response, 'status_code', None), body=body,
                   error=repr(error)[:200], elapsed_ms=clock.ms(), key_material_in_response=leaks(body or ''))
        print(f'{case:4} {note:58} -> handshake {row["handshake_status"]} {body}')
        return log('negative', row)
    row['handshake'] = 'accepted'
    messages = []
    for item in send:
        try:
            await conn.send(item)
        except websockets.ConnectionClosed as closed:
            row['closed_while_sending'] = dict(code=closed.rcvd.code if closed.rcvd else None, sent_items=send.index(item))
            break
    try:
        while True:
            message = await asyncio.wait_for(conn.recv(), wait_s)
            messages.append(dict(t_ms=clock.ms(), msg=message if isinstance(message, str) else f'<binary {len(message)}>'))
            if len(messages) > 40:
                break
    except asyncio.TimeoutError:
        row['still_open_after_s'] = wait_s
        await conn.close()
    except websockets.ConnectionClosed:
        pass
    row.update(close=dict(code=conn.close_code, reason=conn.close_reason), elapsed_ms=clock.ms(),
               messages=[dict(t_ms=m['t_ms'], msg=m['msg'][:400]) for m in messages],
               key_material_in_response=any(leaks(m['msg']) for m in messages))
    print(f'{case:4} {note:58} -> open, {len(messages)} msgs, close={row["close"]} '
          f'{messages[0]["msg"][:150] if messages else ""}')
    return log('negative', row)


def stt_url(**query):
    return f'{WSS}/stt/live?' + urllib.parse.urlencode({'model': 'pulse', 'language': 'en', 'encoding': 'linear16',
                                                         'sample_rate': '16000', **query})


def pcm(seconds=1.0):
    data = CLIP[44:44 + int(32000 * seconds)]
    return [data[i:i + 3200] for i in range(0, len(data), 3200)]


def ws_cases():
    tts = f'{WSS}/tts/live'
    yield ('E01', lambda: ws('E01', 'STT WS no Authorization', '401 at handshake', stt_url(), headers={}))
    yield ('E01', lambda: ws('E01', 'STT WS invalid key', '401 at handshake', stt_url(), headers=auth(BAD_KEY)))
    yield ('E01', lambda: ws('E01', 'TTS WS no Authorization', '401 at handshake', tts, headers={}))
    yield ('E01', lambda: ws('E01', 'TTS WS invalid key', '401 at handshake', tts, headers=auth(BAD_KEY),))
    yield ('E05', lambda: ws('E05', 'TTS WS malformed JSON', 'interpretable error frame or close', tts, send=['{"text": "hi", ']))
    yield ('E05', lambda: ws('E05', 'TTS WS plain text frame', 'interpretable error frame or close', tts, send=['hello']))
    yield ('E05', lambda: ws('E05', 'TTS WS JSON missing voice_id', 'error frame (400-equivalent)', tts,
             send=[json.dumps({'text': 'hi', 'model': 'lightning_v3.1_pro'})]))
    yield ('E05', lambda: ws('E05', 'TTS WS unknown voice_id', 'error frame', tts,
             send=[json.dumps({**TTS_OK, 'voice_id': 'no_such_voice_qa', 'output_format': 'pcm'})]))
    yield ('E05', lambda: ws('E05', 'TTS WS binary frame', 'interpretable error frame or close', tts, send=[b'\x00\x01\x02']))
    yield ('E05', lambda: ws('E05', 'STT WS malformed JSON control message', 'error frame or ignore', stt_url(),
             send=[*pcm(1.0), '{"type": "close_stream"', json.dumps({'type': 'close_stream'})]))
    yield ('E05', lambda: ws('E05', 'STT WS unknown control type', 'error frame or ignore', stt_url(),
             send=[*pcm(1.0), json.dumps({'type': 'qa_unknown'}), json.dumps({'type': 'close_stream'})]))
    yield ('E07', lambda: ws('E07', 'STT WS model=pulse-pro', 'documented: 400 at handshake', stt_url(model='pulse-pro')))
    yield ('E07', lambda: ws('E07', 'STT WS model=not_a_model', 'documented: 400 at handshake', stt_url(model='not_a_model')))
    yield ('E07', lambda: ws('E07', 'STT WS encoding=not_an_encoding', '400 at handshake', stt_url(encoding='not_an_encoding'),
             send=[json.dumps({'type': 'close_stream'})]))
    yield ('E06', lambda: ws('E06', 'STT WS sample_rate=12345 (not in enum)', '400 at handshake', stt_url(sample_rate='12345'),
             send=[json.dumps({'type': 'close_stream'})]))
    yield ('E07', lambda: ws('E07', 'STT WS language=xx', 'error', stt_url(language='xx'), send=[*pcm(1.0), json.dumps({'type': 'close_stream'})]))
    yield ('E05', lambda: ws('E05', 'STT WS control: 1 s audio then valid close_stream', 'is_final + is_last', stt_url(),
             send=[*pcm(1.0), json.dumps({'type': 'close_stream'})]))
    yield ('E05', lambda: ws('E05', 'STT WS malformed JSON only, then wait (no close_stream)', 'error frame or ignore', stt_url(),
             send=[*pcm(1.0), '{"type": "close_stream"'], wait_s=8))
    yield ('E07', lambda: ws('E07', 'STT WS close_stream with zero audio', 'is_last=true, empty transcript', stt_url(),
             send=[json.dumps({'type': 'close_stream'})]))


def http_cases():
    json_h = {**auth(), 'Content-Type': 'application/json'}
    bin_h = {**auth(), 'Content-Type': 'application/octet-stream'}
    stt = '/stt/'
    return [
        ('E01', 'TTS REST no Authorization', '401', 'POST', '/tts', dict(headers={'Content-Type': 'application/json'}, json=TTS_OK)),
        ('E01', 'TTS REST invalid key', '401', 'POST', '/tts', dict(headers={**auth(BAD_KEY), 'Content-Type': 'application/json'}, json=TTS_OK)),
        ('E01', 'TTS REST malformed Authorization (no Bearer)', '401', 'POST', '/tts',
         dict(headers={'Authorization': BAD_KEY, 'Content-Type': 'application/json'}, json=TTS_OK)),
        ('E01', 'STT REST no Authorization', '401', 'POST', stt,
         dict(headers={'Content-Type': 'application/octet-stream'}, params={'model': 'pulse', 'language': 'en'}, data=CLIP)),
        ('E01', 'STT REST invalid key', '401', 'POST', stt,
         dict(headers={**auth(BAD_KEY), 'Content-Type': 'application/octet-stream'}, params={'model': 'pulse', 'language': 'en'}, data=CLIP)),
        ('E01', 'voices list invalid key', '401', 'GET', '/lightning-v3.1-pro/get_voices', dict(headers=auth(BAD_KEY))),
        ('E01', 'voices list no Authorization', '401', 'GET', '/lightning-v3.1-pro/get_voices', dict(headers={})),
        ('E01', 'STT REST invalid key, small body', '401', 'POST', stt,
         dict(headers={**auth(BAD_KEY), 'Content-Type': 'application/octet-stream'}, params={'model': 'pulse', 'language': 'en'}, data=CLIP[:4000])),
        ('E07', 'STT model=not_a_model, small body', '400', 'POST', stt,
         dict(headers=bin_h, params={'model': 'not_a_model', 'language': 'en'}, data=CLIP[:4000])),
        ('E02', 'TTS unknown voice_id', '400 descriptive', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'voice_id': 'no_such_voice_qa'})),
        ('E02', 'TTS standard-only voice on Pro model', "400 'Voice ... is not available on the lightning_v3.1_pro model'", 'POST', '/tts',
         dict(headers=json_h, json={**TTS_OK, 'voice_id': 'STANDARD_ONLY'})),
        ('E03', 'TTS text missing', '400', 'POST', '/tts', dict(headers=json_h, json={k: v for k, v in TTS_OK.items() if k != 'text'})),
        ('E03', 'TTS text empty string', '400', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'text': ''})),
        ('E03', 'TTS text whitespace only', '400 (documented: whitespace-only rejected)', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'text': '   \n '})),
        ('E03', 'TTS invalid model', '400', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'model': 'lightning_v9'})),
        ('E03', 'TTS body not JSON', '400', 'POST', '/tts', dict(headers=json_h, data='{"text": "hi",')),
        ('E04', 'TTS American voice kaitlyn with language=hi', 'docs disagree: 400 vs accepted', 'POST', '/tts',
         dict(headers=json_h, json={**TTS_OK, 'language': 'hi', 'text': 'आपका KYC pending है.'})),
        ('E04', 'TTS Indian voice meher with language=en', 'docs disagree: 400 vs accepted', 'POST', '/tts',
         dict(headers=json_h, json={**TTS_OK, 'voice_id': 'meher', 'language': 'en'})),
        ('E04', 'TTS language=xx (not in enum)', '400', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'language': 'xx'})),
        ('E06', 'TTS sample_rate=12345', '400 (enum 8000/16000/24000/44100)', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'sample_rate': 12345})),
        ('E06', 'TTS sample_rate=48000', '400 (enum 8000/16000/24000/44100)', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'sample_rate': 48000})),
        ('E06', 'TTS speed=5 (documented range 0.5-2.0)', '400', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'speed': 5})),
        ('E06', 'TTS output_format=flac', '400', 'POST', '/tts', dict(headers=json_h, json={**TTS_OK, 'output_format': 'flac'})),
        ('E07', 'STT model missing', '400 (model required)', 'POST', stt, dict(headers=bin_h, params={'language': 'en'}, data=CLIP)),
        ('E07', 'STT model=not_a_model', '400', 'POST', stt, dict(headers=bin_h, params={'model': 'not_a_model', 'language': 'en'}, data=CLIP)),
        ('E07', 'STT pulse-pro language=hi', '400 (Pulse Pro accepts only en)', 'POST', stt, dict(headers=bin_h, params={'model': 'pulse-pro', 'language': 'hi'}, data=CLIP)),
        ('E07', 'STT language=xx', '400 unsupported language', 'POST', stt, dict(headers=bin_h, params={'model': 'pulse', 'language': 'xx'}, data=CLIP)),
        ('E07', 'STT language=te (not in pre-recorded enum)', '400 per reference enum', 'POST', stt, dict(headers=bin_h, params={'model': 'pulse', 'language': 'te'}, data=CLIP)),
        ('E07', 'STT language omitted', 'undocumented default', 'POST', stt, dict(headers=bin_h, params={'model': 'pulse'}, data=CLIP)),
        ('E07', 'STT empty body', '400 NoAudio', 'POST', stt, dict(headers=bin_h, params={'model': 'pulse', 'language': 'en'}, data=b'')),
        ('E07', 'STT non-audio bytes', '400 AudioDecodeError', 'POST', stt,
         dict(headers=bin_h, params={'model': 'pulse', 'language': 'en'}, data=b'this is not audio ' * 200)),
        ('E07', 'STT word_timestamps=True (capitalised)', '400 (lowercase only)', 'POST', stt,
         dict(headers=bin_h, params={'model': 'pulse', 'language': 'en', 'word_timestamps': 'True'}, data=CLIP)),
        ('E07', 'STT JSON body with unreachable url', '400 with a clear message', 'POST', stt,
         dict(headers={**auth(), 'Content-Type': 'application/json'}, params={'model': 'pulse', 'language': 'en'},
              json={'url': 'https://example.invalid/qa.wav'})),
    ]


async def main(only):
    standard = next((v['voiceId'] for v in requests.get(f'{HTTP}/lightning-v3.1/get_voices', headers=auth(), timeout=30).json()['voices']
                     if v['voiceId'] not in {p['voiceId'] for p in requests.get(f'{HTTP}/lightning-v3.1-pro/get_voices', headers=auth(), timeout=30).json()['voices']}), None)
    for case, note, expected, method, path, kwargs in http_cases():
        if args_note or (only and case not in only):
            continue
        if kwargs.get('json', {}).get('voice_id') == 'STANDARD_ONLY':
            kwargs = {**kwargs, 'json': {**kwargs['json'], 'voice_id': standard}}
            note = f'{note} ({standard})'
        http(case, note, expected, method, path, **kwargs)
    for case, job in ws_cases():
        if only and case not in only:
            continue
        if args_note and args_note not in job.__code__.co_consts.__repr__():
            continue
        await job()
        await asyncio.sleep(1.0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--only')
    parser.add_argument('--note', help='run only WebSocket cases whose note contains this text; skips HTTP cases')
    args = parser.parse_args()
    args_note = args.note
    asyncio.run(main(set(args.only.split(',')) if args.only else None))
