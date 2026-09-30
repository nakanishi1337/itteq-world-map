#!/usr/bin/env python3
"""Collect official articles, resolve destinations, and append visits to the shared episode dataset."""
import argparse
import calendar
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
    lines = ['# 保存済みの放送履歴（今回のAI処理一覧ではありません）', '',
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


def month_before(day):
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def run_report(since, today, runs, client, warnings):
    ai = [r for r in runs if r['apiRequests']]
    reused = [r['date'] for r in runs if r['mode'] == 'unchanged']
    cached = [r['date'] for r in runs if r['mode'] == 'cache']
    pending = [r for r in runs if r['decision']['status'] == 'pending']
    lines = ['# 今回の更新結果', '', f'対象期間: {since} ～ {today}（両端を含む）', '',
             f'AI呼び出し: **{client.calls}回** / AI処理対象: {len(ai)}日 / 変更なし: {len(reused)}日 / APIキャッシュ利用: {len(cached)}日 / 保留: {len(pending)}日', '',
             '対象期間外の保存済みデータは保持し、AI処理していません。', '',
             '## 今回AIに送った放送日', '']
    if ai:
        lines += ['| 放送日 | 再処理のきっかけ | 結果 | 今回取得した企画 |', '|---|---|---|---|']
        for r in ai:
            d = r['decision']
            titles = '、'.join(p['project'] for p in d['projects']) or '企画なし'
            result = '取得成功'
            if d['status'] == 'pending':
                titles = '—（以前のデータを保持）'
                result = '保留: ' + d['reason']
            titles = titles.replace('|', '／').replace('\n', ' ')
            lines.append(f"| {r['date']} | {r['trigger']} | {result} | {titles} |")
    else:
        lines += ['なし。今回AIへのリクエストはありません。']
    lines += ['', '## AIを呼ばず再利用した放送日', '',
              '変更なし: ' + ('、'.join(reused) or 'なし'), '',
              '保存済みAPI回答: ' + ('、'.join(cached) or 'なし')]
    no_request = [r for r in pending if not r['apiRequests']]
    if no_request:
        lines += ['', '## API呼び出し前の保留', '']
        lines += [f"- {r['date']}: {r['decision']['reason']}" for r in no_request]
    if client.usage:
        lines += ['', f"トークン使用量: 入力 {client.usage.get('input_tokens', 0)} / 出力 {client.usage.get('output_tokens', 0)}"]
    if warnings:
        lines += ['', '## 取得上の注意', ''] + ['- ' + w for w in sorted(set(warnings))]
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path)
    p.add_argument('--since', type=dt.date.fromisoformat, help='対象期間の開始日。省略時は--todayの1か月前（前月同日、存在しなければ月末）')
    p.add_argument('--today', type=dt.date.fromisoformat, default=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date())
    p.add_argument('--cache-dir', type=Path, default=ROOT / '.cache/ntv')
    p.add_argument('--output-dir', type=Path, help='検証用出力先。省略時はリポジトリのデータを更新')
    p.add_argument('--offline', action='store_true', help='--input必須。通信せず、番組表・OpenAI回答は保存済み資料のみ')
    p.add_argument('--validate-only', action='store_true')
    args = p.parse_args()
    args.since = args.since or month_before(args.today)
    if args.since > args.today:
        p.error("--since must not be later than --today")
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
    runs = []
    for date, documents in sorted(grouped.items()):
        calls, hits = client.calls, client.hits
        d = decide(date, documents, client, old.get(date))
        if d is old.get(date):
            reused += 1
        mode = 'ai' if client.calls > calls else 'cache' if client.hits > hits else 'unchanged' if d is old.get(date) else 'pending'
        trigger = '未処理' if date not in old else '前回保留の再試行' if old[date]['status'] == 'pending' else '資料・抽出設定の変更'
        runs.append({'date': date, 'mode': mode, 'trigger': trigger, 'apiRequests': client.calls - calls, 'decision': d})
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
    (args.cache_dir / 'run.md').write_text(run_report(args.since, args.today, runs, client, warnings))
    stats = {'since': args.since.isoformat(), 'today': args.today.isoformat(), 'processedDates': [r['date'] for r in runs if r['apiRequests']], 'apiRequests': client.calls, 'cacheHits': client.hits, 'unchangedBroadcasts': reused, 'usage': client.usage,
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
