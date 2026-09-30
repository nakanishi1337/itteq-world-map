#!/usr/bin/env python3
"""公式予告を企画単位で抽出する。訪問実績や出演者と国の対応は推定しない。"""
import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.request

SOURCE = 'https://www.ntv.co.jp/q/articles.json'
ROOT = Path(__file__).resolve().parents[1]
PREVIEW = re.compile(r'(\d{1,2})月(\d{1,2})日の[「『]イッテ[QＱ][!！]?[」』]は')


class Sections(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []
        self.current = None
        self.heading = False
        self.ignored = 0
        self.preamble = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored += 1
        if self.ignored:
            return
        if re.fullmatch(r'h[1-6]', tag):
            self.current = {'heading': [], 'body': []}
            self.sections.append(self.current)
            self.heading = True
        elif tag in ('br', 'p', 'div', 'li'):
            self.handle_data('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignored:
            self.ignored -= 1
        elif re.fullmatch(r'h[1-6]', tag):
            self.heading = False
        elif tag in ('p', 'div', 'li'):
            self.handle_data('\n')

    def handle_data(self, text):
        if self.ignored:
            return
        if self.current is None:
            self.preamble.append(text)
        else:
            self.current['heading' if self.heading else 'body'].append(text)


def clean(parts):
    return '\n'.join(line.strip() for line in ''.join(parts).splitlines() if line.strip())


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


def collect(articles, since=None):
    if not isinstance(articles, list):
        raise ValueError('記事一覧が配列ではありません')
    records, issues, seen = [], [], set()
    preview_count = 0
    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get('data'), dict):
            raise ValueError('記事データの構造が変わっています')
        data = article['data']
        title = data.get('title')
        if not isinstance(title, str):
            raise ValueError('記事タイトルがありません')
        if not PREVIEW.search(title):
            continue
        preview_count += 1
        article_id = article.get('item_id')
        if not isinstance(article_id, str) or not re.fullmatch('[a-zA-Z0-9]+', article_id):
            raise ValueError('記事IDが不正です')
        if article_id in seen:
            raise ValueError(f'記事IDが重複しています: {article_id}')
        seen.add(article_id)
        content_id = article.get('content_id')
        if not isinstance(content_id, int):
            raise ValueError('content_idが不正です')
        url = f'https://www.ntv.co.jp/q/articles/{content_id}{article_id}.html'
        published = article.get('publish_date') or article.get('display_date') or ''
        date = broadcast_date(title, published)
        if since and date and date < since:
            continue
        body = data.get('body')
        if not isinstance(body, str):
            issues.append({'articleId': article_id, 'source': url, 'reason': 'missing_body'})
            continue
        parser = Sections()
        parser.feed(body)
        if clean(parser.preamble):
            issues.append({'articleId': article_id, 'source': url, 'reason': 'text_before_heading', 'text': clean(parser.preamble)})
        if not parser.sections:
            issues.append({'articleId': article_id, 'source': url, 'reason': 'missing_headings', 'bodyHtml': body})
        for index, section in enumerate(parser.sections, 1):
            project, text = clean(section['heading']), clean(section['body'])
            performers = cast(text)
            warnings = []
            for missing, reason in ((not date, 'unknown_broadcast_date'), (not project, 'missing_project'), (not performers, 'missing_performers')):
                if missing:
                    warnings.append(reason)
            records.append({'articleId': article_id, 'projectIndex': index, 'source': url, 'publishedAt': published, 'date': date, 'project': project, 'performers': performers, 'body': text, 'reviewReasons': warnings})
    if not preview_count:
        raise ValueError('予告記事が0件です。入力形式を確認してください')
    if not records and issues:
        raise ValueError('企画を抽出できませんでした: ' + json.dumps(issues, ensure_ascii=False))
    records.sort(key=lambda x: (x['date'] or '9999-12-31', x['articleId'], x['projectIndex']))
    return {'schemaVersion': 2, 'source': SOURCE, 'summary': {'articles': len(articles), 'previewArticles': preview_count, 'projects': len(records), 'projectsWithWarnings': sum(bool(r['reviewReasons']) for r in records), 'articleIssues': len(issues)}, 'records': records, 'articleIssues': issues}


def check_output(path):
    resolved = path.resolve()
    if resolved.is_relative_to((ROOT / 'src/data').resolve()):
        raise ValueError('src/data 配下には出力できません')
    return resolved


def write_output(path, content):
    path = check_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = stream.name
            stream.write(content)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='保存済みの公式記事JSON')
    parser.add_argument('--output', type=Path, help='指定しなければ標準出力')
    parser.add_argument('--since', type=dt.date.fromisoformat, help='放送日の下限 YYYY-MM-DD（不明日は要確認として保持）')
    args = parser.parse_args()
    try:
        if args.output:
            check_output(args.output)
            if args.input and args.output.resolve() == args.input.resolve():
                raise ValueError('入力ファイルへの上書きはできません')
        if args.input:
            articles = json.loads(args.input.read_text(encoding='utf-8'))
        else:
            request = urllib.request.Request(SOURCE, headers={'User-Agent': 'itteq-world-map/0.1'})
            with urllib.request.urlopen(request, timeout=30) as response:
                articles = json.load(response)
        result = collect(articles, args.since.isoformat() if args.since else None)
        content = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            write_output(args.output, content)
        else:
            sys.stdout.write(content)
        print(json.dumps(result['summary'], ensure_ascii=False), file=sys.stderr)
        for reason in sorted({reason for row in result['records'] for reason in row['reviewReasons']}):
            print(f"{reason}: {sum(reason in row['reviewReasons'] for row in result['records'])}", file=sys.stderr)
    except (OSError, ValueError, TypeError) as error:
        print(f'取得・解析失敗: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
