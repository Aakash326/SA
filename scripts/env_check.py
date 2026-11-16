"""Stage 0: record the client environment to results/environment.json."""
import json
import platform
import socket
import subprocess
import sys

import requests
import websockets

from common import HOST, RESULTS, api_key, stamps

api_key()
ffmpeg = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True).stdout.splitlines()[0]
env = dict(**stamps(), os=platform.platform(), python=sys.version.split()[0], requests=requests.__version__,
           websockets=websockets.__version__, ffmpeg=ffmpeg, host=HOST,
           resolved=sorted({a[4][0] for a in socket.getaddrinfo(HOST, 443)}), key_present=True,
           network_note='Fill in city / ISP manually; not collected automatically.')
RESULTS.mkdir(exist_ok=True)
(RESULTS / 'environment.json').write_text(json.dumps(env, indent=1), encoding='utf-8')
print(json.dumps(env, indent=1))
