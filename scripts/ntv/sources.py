import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse
from .common import digest, request, read_json, write_json
import unicodedata

NTV = 'https://www.ntv.co.jp/q/articles.json'
PREVIEW = re.compile(r'(\d{1,2})月(\d{1,2})日の[「『]イッテ[QＱ][!！]?[」』]は')

def normalize(text):
    return unicodedata.normalize('NFKC', text).strip()


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


def broadcast_date(title, published):
    match = PREVIEW.search(title)
    try:
        day = dt.date.fromisoformat(published[:10])
    except (TypeError, ValueError):
        return None
    if not match:
        return None
    candidates = []
    for year in (day.year, day.year + 1):
        try:
            value = dt.date(year, int(match[1]), int(match[2]))
        except ValueError:
            continue
        if 0 <= (value - day).days <= 31:
            candidates.append(value.isoformat())
    return candidates[0] if len(candidates) == 1 else None


def articles_documents(articles):
    if not isinstance(articles, list) or not articles:
        raise ValueError('記事一覧が空または不正です')
    docs = []
    for article in articles:
        data = article['data']
        title = data['title']
        if PREVIEW.search(title):
            kind = 'preview'
            date = broadcast_date(title, article.get('publish_date') or article.get('display_date') or '')
            if not date:
                raise ValueError('予告の放送日を取得できません: ' + title)
        elif any(t.get('text') == 'OAまとめ' for t in data.get('tags', [])):
            kind = 'summary'
            date = article['display_date'][:10]
            dt.date.fromisoformat(date)
        else:
            continue
        if not isinstance(data.get('body'), str) or not data['body'].strip():
            raise ValueError('記事本文がありません: ' + title)
        docs.append({'kind': kind, 'date': date, 'title': title, 'text': plain(data['body']),
                     'url': f"https://www.ntv.co.jp/q/articles/{article['content_id']}{article['item_id']}.html"})
    if not docs:
        raise ValueError('予告・OAまとめがありません')
    return docs


def parse_schedule(html, url, expected_date=None):
    text = plain(html)
    date = re.search(r'(\d{4})年(\d{2})月(\d{2})日[^\n]*?(\d{1,2})時(\d{2})分', text)
    if not date or not re.search(r'イッテ[QＱ]', text) or '再放送' in text or '[再]' in normalize(text):
        return None
    day = f'{date[1]}-{date[2]}-{date[3]}'
    # Evening original broadcast, including longer specials.
    if not 18 <= int(date[4]) <= 21 or (expected_date and day != expected_date):
        return None
    return {'kind': 'schedule', 'id': digest(url), 'date': day, 'title': '日本海テレビ番組表', 'text': text, 'url': url}


def schedules(cache, warnings):
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
