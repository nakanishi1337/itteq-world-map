#!/usr/bin/env python3
"""Collect official articles, resolve destinations, and append visits to the shared episode dataset."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
from broadcasts.common import ROOT, split_episodes, read_json, write_json, request
from broadcasts.openai import OpenAI
from broadcasts.pipeline import COUNTRIES, decide, make_episodes
from broadcasts.sources import NTV, articles_documents, schedules


def validate(episodes):
    seen = set()
    for e in episodes:
        dt.date.fromisoformat(e['date'])
        key = (e['projectId'], e['countryCode'])
        if e['countryCode'] not in COUNTRIES or key in seen or not isinstance(e['performers'], list) or not e['project'] or not e['source'].startswith(('https://www.ntv.co.jp/q/articles/', 'https://www.nkt-tv.co.jp/program/')):
            raise ValueError('Invalid or duplicate NTV episode')
        seen.add(key)


def report(decisions, warnings):
    accepted = sum(d['status'] == 'accepted' for d in decisions)
    lines = ['# 日テレ放送データの更新状況', '',
             f'放送日: 処理済み {accepted} / 保留 {len(decisions) - accepted}', '',
             '放送日ごとの予告・OAまとめ・番組表をAIで統合します。検証後にmainへ自動pushします。', '',
             '| 放送日 | 状態 | 企画 | 国 | 処理結果 |', '|---|---|---|---|---|']
    for d in decisions:
        result = {'openai_projects': '企画を取得', 'openai_empty': '取得できた企画なし'}.get(d['reason'], '取得保留: ' + d['reason'])
        for p in d['projects'] or [None]:
            title = p['project'].replace('|', '／').replace('\n', ' ') if p else '—'
            if p:
                title = f"[{title}]({p['sourceUrls'][0]})"
            countries = (', '.join(p['countries']) or '—') if p else '—'
            lines.append(f"| {d['date']} | {d['status']} | {title} | {countries} | {result} |")
    if warnings:
        lines += ['## 取得上の注意', ''] + ['- ' + w for w in sorted(set(warnings))]
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path)
    p.add_argument('--since', type=dt.date.fromisoformat, default=dt.date(2026, 7, 27))
    p.add_argument('--today', type=dt.date.fromisoformat, default=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date())
    p.add_argument('--cache-dir', type=Path, default=ROOT / '.cache/ntv')
    p.add_argument('--output-dir', type=Path, help='検証用出力先。省略時はリポジトリのデータを更新')
    p.add_argument('--offline', action='store_true', help='--input必須。通信せず、番組表・OpenAI回答は保存済み資料のみ')
    p.add_argument('--validate-only', action='store_true')
    args = p.parse_args()
    baseline = ROOT / 'src/data/episodes.json'
    initial_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    legacy, _ = split_episodes(read_json(baseline))
    dest = args.output_dir or ROOT / 'data/broadcasts/generated'
    episode_path = (dest / 'episodes.json') if args.output_dir else baseline
    if args.validate_only:
        _, additions = split_episodes(read_json(episode_path))
        validate(additions)
        print('Data validation passed; original Wikipedia rows unchanged')
        return 0
    if args.offline and not args.input:
        p.error('--offline requires --input')
    articles = read_json(args.input) if args.input else json.loads(request(NTV))
    # Validate source before any published outputs are changed.
    docs = articles_documents(articles)
    write_json(args.cache_dir / 'articles.json', articles)
    warnings = []
    if args.offline:
        docs += [read_json(f) for f in sorted((args.cache_dir / 'schedules').glob('*.json'))]
    else:
        docs += schedules(args.cache_dir, warnings)
    old_manifest = read_json(dest / 'decisions.json', {})
    # Old per-project decisions are replaced date by date after successful extraction.
    old = {d['date']: d for d in old_manifest.get('broadcasts', [])}
    _, previous = split_episodes(read_json(episode_path, legacy))
    client = OpenAI(args.cache_dir / 'openai', offline=args.offline)
    grouped = {}
    for doc in docs:
        if args.since.isoformat() <= doc['date'] <= args.today.isoformat():
            grouped.setdefault(doc['date'], []).append(doc)
    decisions = dict(old)
    reused = 0
    for date, documents in sorted(grouped.items()):
        d = decide(date, documents, client, old.get(date))
        if d is old.get(date):
            reused += 1
        decisions[date] = d
    decisions = sorted(decisions.values(), key=lambda d: d['date'])
    # Dates not collected in this run keep their existing rows, including legacy additions.
    active = [d for d in decisions if d['date'] in grouped]
    episodes = make_episodes(active, previous)
    validate(episodes)
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != initial_hash:
        raise ValueError('既存データが実行中に変更されました')
    manifest = {'schemaVersion': 4, 'broadcasts': decisions}
    markdown = report(decisions, warnings)
    # Prepare all data before replacing output files. A failed validation never publishes data.
    write_json(episode_path, legacy + episodes)
    write_json(dest / 'decisions.json', manifest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'report.md').write_text(markdown)
    stats = {'apiRequests': client.calls, 'cacheHits': client.hits, 'unchangedBroadcasts': reused, 'usage': client.usage,
             'episodeRecords': len(episodes), 'totalEpisodeRecords': len(legacy) + len(episodes), 'broadcasts': len(decisions), 'warnings': warnings}
    write_json(args.cache_dir / 'run.json', stats)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('更新中止: ' + str(error), file=sys.stderr)
        sys.exit(1)
