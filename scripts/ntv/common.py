import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASELINE = 'e5652af28e6f81d8ab45a654207aa23933ff6f9888aff4e2047ad1778f5dcbcc'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
            temp = f.name
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def request(url, payload=None, key=None):
    headers = {'User-Agent': 'itteq-world-map/0.2'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload, ensure_ascii=False).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as r:
                return r.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504, 529) or attempt == 2:
                raise
            retry = error.headers.get('Retry-After', '')
            time.sleep(min(float(retry), 30) if retry.isdigit() else 2 ** attempt)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
