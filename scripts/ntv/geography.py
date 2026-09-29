import re
import unicodedata
from .common import ROOT, read_json, digest

PLACES = read_json(ROOT / 'data/ntv/places.json')
CITIES = read_json(ROOT / 'data/ntv/cities.json')
CITIES_HASH = digest(CITIES)
ALIASES = {n: [v['code']] for n, v in PLACES['aliases'].items()}
for name, codes in CITIES['aliases'].items():
    if name not in PLACES['aliases'] or PLACES['aliases'][name]['kind'] == 'city':
        ALIASES[name] = sorted(set(ALIASES.get(name, []) + codes))
# Country and region entries are explicit policy; city homonyms remain ambiguous.
TRIE = {}
for name, codes in ALIASES.items():
    node = TRIE
    for char in name.casefold():
        node = node.setdefault(char, {})
    node.setdefault('', set()).update(codes)


def normalize(text):
    return unicodedata.normalize('NFKC', text).strip()


def lookup(text, start):
    node, best = TRIE, None
    for pos in range(start, len(text)):
        char = text[pos].casefold()
        if char not in node:
            break
        node = node[char]
        if '' in node:
            best = (pos + 1, sorted(node['']))
    return best


def candidates(text):
    result, pos = [], 0
    while pos < len(text):
        match = lookup(text, pos)
        if not match:
            pos += 1
            continue
        end, codes = match
        place = text[pos:end]
        before, after = text[pos-1:pos] if pos else '', text[end:end+1]
        katakana = any(re.fullmatch('[ァ-ヺー]', c) for c in (before, after) if c)
        latin = re.search('[A-Za-z]', place) and any(re.fullmatch('[A-Za-z]', c) for c in (before, after) if c)
        han = re.fullmatch('[一-龯々]+', place) and any(re.fullmatch('[一-龯々]', c) for c in (before, after) if c)
        if not katakana and not latin and not han:
            for code in codes:
                if code in PLACES['names']:
                    result.append({'place': place, 'countryCode': code, 'start': pos, 'end': end, 'ambiguous': len(codes) > 1})
        pos = end
    return result


def heading_places(title):
    """Only accept a complete trailing `in <place list>` and unambiguous mappings."""
    match = re.search(r'(?i)(?<![a-z])in\s+(.+)$', normalize(title))
    if not match:
        return []
    suffix, result = match[1].strip(), []
    while suffix:
        hit = lookup(suffix, 0)
        if hit is None:
            return []
        end, codes = hit
        if len(codes) != 1 or codes[0] not in PLACES['names']:
            return []
        result.append({'place': suffix[:end], 'countryCode': codes[0]})
        suffix = suffix[end:].strip()
        if suffix:
            sep = re.match(r'^[・、,&＆/／と]+\s*', suffix)
            if not sep:
                return []
            suffix = suffix[sep.end():]
            if not suffix:
                return []
    return result
