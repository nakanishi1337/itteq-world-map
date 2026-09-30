import datetime as dt
from html.parser import HTMLParser
import re
import runpy
from urllib.parse import urljoin, urlparse
from .common import ROOT, digest, request, read_json, write_json
from .geography import normalize

NTV = 'https://www.ntv.co.jp/q/articles.json'
PREVIEWS = runpy.run_path(str(ROOT / 'scripts/collect-ntv-previews.py'))


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
        self.links = []
        self.link = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if self.skip:
            return
        if tag in ('br', 'p', 'div', 'h1', 'h2', 'h3', 'dt', 'dd', 'li'):
            self.parts.append('\n')
        if tag == 'a':
            self.link = [dict(attrs).get('href', ''), []]

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
        if tag == 'a' and self.link:
            self.links.append((self.link[0], ''.join(self.link[1])))
            self.link = None
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'dt', 'dd', 'li'):
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)
            if self.link:
                self.link[1].append(text)


def plain(html):
    parser = Text()
    parser.feed(html)
    return '\n'.join(x.strip() for x in ''.join(parser.parts).splitlines() if x.strip())


def project_key(title):
    return re.sub(r'[\W_]+', '', normalize(title)).lower()


def cast(body):
    # Continuation lines are consumed only after a trailing list separator.
    raw, continuing = [], False
    for line in body.splitlines():
        match = re.match(r'^(?:出演者|スペシャルゲスト|ゲスト)\s*[：:]\s*(.*)', line)
        if match:
            raw.append(match[1])
        elif continuing and not line.startswith(('※', 'スタジオ')):
            raw.append(line)
        else:
            continuing = False
            continue
        continuing = bool(re.search(r'[、・，/]\s*$', line))
    # Preserve Latin spelling such as Kōki, and split Japanese separators only.
    value = '、'.join(raw)
    parts, current, depth = [], '', 0
    for ch in value:
        if ch in '(（': depth += 1
        if ch in ')）': depth = max(0, depth - 1)
        if ch in '、・，／/' and not depth:
            if current.strip(): parts.append(current.strip())
            current = ''
        else:
            current += ch
    if current.strip(): parts.append(current.strip())
    return list(dict.fromkeys(parts))


def previews(articles):
    result = PREVIEWS['collect'](articles)
    if result['articleIssues']:
        raise ValueError('予告記事の構造異常: ' + str(result['articleIssues']))
    for r in result['records']:
        r['performers'] = cast(r['body'])
        r['id'] = r['articleId'] + ':' + str(r['projectIndex'])
    return result['records']


def summaries(articles):
    result = []
    for a in articles:
        data = a.get('data', {})
        if not any(t.get('text') == 'OAまとめ' for t in data.get('tags', [])):
            continue
        date = a.get('display_date', '')[:10]
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            continue
        if not isinstance(data.get('body'), str):
            raise ValueError('OAまとめの本文がありません')
        result.append({'id': a['item_id'], 'title': data['title'], 'date': date,
                       'text': plain(data['body']), 'kind': 'summary',
                       'dateBasis': 'publication_date_candidate',
                       'url': f"https://www.ntv.co.jp/q/articles/{a['content_id']}{a['item_id']}.html"})
    return result


def parse_schedule(html, url, expected_date=None):
    parser = Text()
    parser.feed(html)
    text = plain(html)
    date = re.search(r'(\d{4})年(\d{2})月(\d{2})日[^\n]*?(\d{1,2})時(\d{2})分', text)
    if not date or not re.search(r'イッテ[QＱ]', text) or '再放送' in text or '[再]' in normalize(text):
        return None
    day = f'{date[1]}-{date[2]}-{date[3]}'
    # Evening original broadcast, including longer specials.
    if not 18 <= int(date[4]) <= 21 or (expected_date and day != expected_date):
        return None
    return {'kind': 'schedule', 'id': digest(url), 'date': day, 'title': '日本海テレビ番組表', 'text': text, 'url': url}


def schedules(cache, warnings, today, manual):
    folder = cache / 'schedules'
    docs = {d['url']: d for p in sorted(folder.glob('*.json')) if (d := read_json(p))}
    urls = {}
    # Capture the currently published listing. Archived dates are not brute-forced.
    try:
        parser = Text()
        parser.feed(request('https://www.nkt-tv.co.jp/program/'))
        for href, label in parser.links:
            if re.search(r'イッテ[QＱ]', label) and 'detail.php?' in href:
                url = urljoin('https://www.nkt-tv.co.jp/program/', href)
                if urlparse(url).netloc == 'www.nkt-tv.co.jp':
                    urls[url] = None
    except OSError:
        warnings.append('番組表一覧の取得失敗。保存済み資料のみ利用')
    for entry in manual:
        if entry['url'].startswith('https://www.nkt-tv.co.jp/program/detail.php?'):
            urls[entry['url']] = entry['date']
    for url, expected in sorted(urls.items()):
        try:
            doc = parse_schedule(request(url), url, expected)
            if doc:
                docs[url] = doc
                write_json(folder / (digest(url) + '.json'), doc)
            else:
                warnings.append('番組表の日付・番組・時間帯を確認できません: ' + url)
        except OSError:
            warnings.append('番組表詳細の取得失敗: ' + url)
    return list(docs.values())
