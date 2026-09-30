import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LEGACY_COUNT = 1376
LEGACY_HASH = '59735f908923a56f9e29ac16aeb7305fbeafe74ff90b2a70baf894789a9ddf97'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def split_episodes(episodes):
    """The original ordered Wikipedia rows remain intact at the start of the shared file."""
    if not isinstance(episodes, list) or digest(episodes[:LEGACY_COUNT]) != LEGACY_HASH:
        raise ValueError('Wikipedia由来の既存データが変更されています')
    additions = episodes[LEGACY_COUNT:]
    if any(not isinstance(e, dict) or not e.get('projectId') for e in additions):
        raise ValueError('追加データには企画IDが必要です')
    return episodes[:LEGACY_COUNT], additions


def restore_pending_episodes(current, pending, original):
    """Three-way comparison of appended data, preserving the original Wikipedia records."""
    legacy, current_additions = split_episodes(current)
    _, pending_additions = split_episodes(pending)
    _, original_additions = split_episodes(original)
    if current_additions != original_additions and pending_additions != original_additions and current_additions != pending_additions:
        raise ValueError('Visit data changed on both main and the pending PR')
    return legacy + (current_additions if pending_additions == original_additions else pending_additions)


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


def request(url, payload=None, key=None, timeout=30):
    headers = {'User-Agent': 'itteq-world-map/0.2'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload, ensure_ascii=False).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as r:
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
