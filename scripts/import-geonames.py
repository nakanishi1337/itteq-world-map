#!/usr/bin/env python3
"""Refresh the reviewed offline city gazetteer. Never run automatically in weekly CI."""
import argparse
import collections
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile
from ntv.common import ROOT, write_json

URL = 'https://download.geonames.org/export/dump/cities15000.zip'


def build(raw):
    rows, canonical = [], collections.defaultdict(set)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for line in z.read('cities15000.txt').decode().splitlines():
            f = line.split('\t')
            if len(f) != 19 or not re.fullmatch('[A-Z]{2}', f[8]):
                raise ValueError('Invalid GeoNames row')
            names = {f[1], f[2]}
            for name in f[3].split(','):
                # Unlabelled alternates: retain kana forms, plus Japanese domestic names.
                if re.search('[ぁ-ゖァ-ヺ]', name) or (f[8] == 'JP' and re.fullmatch('[一-龯々ヶぁ-ゖァ-ヺー]+', name)):
                    names.add(name)
            names = {n for n in names if 2 <= len(n) <= 70 and not re.search(r'[\n\t<>]', n)}
            canonical[f[2].casefold()].add(f[8])
            rows.append((f[2].casefold(), names, f[8]))
    aliases = collections.defaultdict(set)
    for primary, names, code in rows:
        for name in names:
            # Share homonym country candidates even when only one city's Japanese alias is present.
            aliases[name].update(canonical[primary])
    return {'source': URL, 'license': 'CC BY 4.0', 'sourceSha256': hashlib.sha256(raw).hexdigest(),
            'cityCount': len(rows), 'aliases': {n: sorted(c) for n, c in sorted(aliases.items())}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zip', type=Path)
    p.add_argument('--output', type=Path, default=ROOT / 'data/ntv/cities.json')
    a = p.parse_args()
    raw = a.zip.read_bytes() if a.zip else urllib.request.urlopen(URL, timeout=30).read()
    result = build(raw)
    write_json(a.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'aliases'}))
    print('aliases:', len(result['aliases']))


if __name__ == '__main__':
    main()
