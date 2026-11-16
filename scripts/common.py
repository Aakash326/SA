"""Shared helpers: key loading, redaction, IST timestamps, JSONL evidence logging."""
import datetime as dt
import hashlib
import json
import os
import pathlib
import struct
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'results'
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


load_env()
HOST = os.environ.get('SMALLEST_HOST', 'api.smallest.ai')
HTTP = f'https://{HOST}/waves/v1'
WSS = f'wss://{HOST}/waves/v1'


def api_key():
    key = os.environ.get('SMALLEST_API_KEY', '')
    if not key:
        raise SystemExit('SMALLEST_API_KEY missing: copy .env.example to .env')
    return key


def auth(key=None):
    return {'Authorization': f'Bearer {key if key is not None else api_key()}'}


def redact(value):
    """Remove the key from anything that is about to be written to disk."""
    key = os.environ.get('SMALLEST_API_KEY', '')
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if key:
        text = text.replace(key, '<REDACTED>')
    return text if isinstance(value, str) else json.loads(text)


def stamps():
    now = dt.datetime.now(dt.timezone.utc)
    return {'ts_utc': now.isoformat(timespec='milliseconds'),
            'ts_ist': now.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + ' IST'}


def sha256(data):
    if isinstance(data, (str, pathlib.Path)):
        data = pathlib.Path(data).read_bytes()
    return hashlib.sha256(data).hexdigest()


def log(name, row):
    """Append one evidence row to results/<name>.jsonl (key redacted)."""
    RESULTS.mkdir(exist_ok=True)
    row = redact({**stamps(), 'host': HOST, **row})
    with open(RESULTS / f'{name}.jsonl', 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    return row


def read_jsonl(name):
    path = RESULTS / f'{name}.jsonl'
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def body_excerpt(response, limit=600):
    """Text of an HTTP response body for logs; binary bodies are summarised."""
    ctype = response.headers.get('content-type', '')
    if 'json' in ctype or 'text' in ctype:
        return response.text[:limit]
    head = response.content[:16]
    try:
        text = response.content[:limit].decode('utf-8')
        if text.isprintable() or text.strip().startswith(('{', '[')):
            return text
    except UnicodeDecodeError:
        pass
    return f'<binary {len(response.content)} bytes, head={head.hex()}>'


KEEP_HEADERS = ('date', 'content-type', 'content-length', 'retry-after', 'x-request-id', 'x-session-id',
                'x-external-session-id', 'x-external-request-id', 'www-authenticate')


def headers_of(response):
    found = {k.lower(): v for k, v in response.headers.items()}
    kept = {k: v for k, v in found.items() if k in KEEP_HEADERS or 'ratelimit' in k or 'rate-limit' in k}
    return kept


def wav_info(data):
    """Parse a RIFF/WAVE byte string. Returns None when it is not a WAV."""
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        return None
    pos, fmt, frames = 12, None, None
    while pos + 8 <= len(data):
        tag, size = data[pos:pos + 4], struct.unpack('<I', data[pos + 4:pos + 8])[0]
        if tag == b'fmt ':
            code, channels, rate, _, _, bits = struct.unpack('<HHIIHH', data[pos + 8:pos + 24])
            fmt = dict(format_code=code, channels=channels, sample_rate=rate, bits=bits)
        elif tag == b'data':
            frames = min(size, len(data) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    if not fmt or frames is None:
        return None
    width = fmt['channels'] * fmt['bits'] // 8
    return {**fmt, 'data_bytes': frames, 'duration_s': round(frames / (fmt['sample_rate'] * width), 3) if width else None}


def pcm_from_wav(path):
    """Return (pcm_bytes, sample_rate) without the WAV header."""
    data = pathlib.Path(path).read_bytes()
    info = wav_info(data)
    if not info:
        raise ValueError(f'{path} is not a WAV file')
    start = data.find(b'data') + 8
    return data[start:start + info['data_bytes']], info['sample_rate']


def wrap_wav(pcm, rate, channels=1, bits=16):
    width = channels * bits // 8
    return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
            struct.pack('<IHHIIHH', 16, 1, channels, rate, rate * width, width, bits) +
            b'data' + struct.pack('<I', len(pcm)) + pcm)


class Clock:
    """Monotonic stopwatch in milliseconds."""

    def __init__(self):
        self.start = time.perf_counter()

    def ms(self):
        return round((time.perf_counter() - self.start) * 1000, 1)


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 1)
