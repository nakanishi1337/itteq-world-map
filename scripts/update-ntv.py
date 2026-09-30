#!/usr/bin/env python3
"""Collect official articles, resolve destinations, and append visits to the shared episode dataset."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
from ntv.common import ROOT, split_episodes, digest, read_json, write_json, request
from ntv.openai import OpenAI
from ntv.geography import PLACES
from ntv.pipeline import decide, make_episodes
from ntv.summary import decide_summary, reconcile
from ntv.sources import NTV, previews, summaries, schedules, project_key


def validate(episodes):
    seen = set()
    for e in episodes:
        dt.date.fromisoformat(e['date'])
        key = (e['projectId'], e['countryCode'])
        if e['countryCode'] not in PLACES['names'] or key in seen or not e['performers'] or not e['project'] or not e['source'].startswith('https://www.ntv.co.jp/q/articles/'):
            raise ValueError('Invalid or duplicate NTV episode')
        seen.add(key)


def report(decisions, gaps, warnings):
    counts = {s: sum(d['status'] == s for d in decisions) for s in ('accepted', 'pending', 'excluded')}
    lines = ['# 日テレ放送データの更新状況', '',
             f"企画・記事: 採用 {counts['accepted']} / 保留 {counts['pending']} / 除外 {counts['excluded']}",
             f'OAまとめの抽出保留: {len(gaps)}件（上記の保留に含みます）',
             f"見出し確定 {sum(d['status']=='accepted' and d['method']=='heading' for d in decisions)} / OpenAI確定 {sum(d['status']=='accepted' and d['method'] in ('openai', 'openai_summary') for d in decisions)}", '',
             'GitHub Actionsでは検証後に更新データをmainへ自動コミット・pushします。', '',
             '予告由来は企画の出演者一覧、OAまとめ由来はAIが抽出した国ごとの出演者を使用します。', '',
             '| 放送日 | 企画 | 判定 | 国 | 根拠・保留理由 |', '|---|---|---|---|---|']
    for d in decisions:
        title = d['project'].replace('|', '／').replace('\n', ' ')
        countries = ', '.join(c['countryCode'] for c in d['countries']) or '—'
        links = ' '.join(f"[根拠]({u})" for u in sorted({c['evidence']['url'] for c in d['countries']}))
        lines.append(f"| {d['date']} | [{title}]({d['source']}) | {d['status']} | {countries} | {d['reason']} {links} |")
    if warnings:
        lines += ['', '## 取得上の注意', ''] + ['- ' + w for w in sorted(set(warnings))]
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
    dest = args.output_dir or ROOT / 'data/ntv/generated'
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
    rows = previews(articles)
    docs = summaries(articles)
    write_json(args.cache_dir / 'articles.json', articles)
    warnings = []
    references = read_json(ROOT / 'data/ntv/references.json', [])
    if args.offline:
        schedule_docs = [read_json(f) for f in sorted((args.cache_dir / 'schedules').glob('*.json'))]
    else:
        schedule_docs = schedules(args.cache_dir, warnings, references)
    docs += schedule_docs
    for ref in references:
        if ref.get('text'):
            docs.append({'id': digest(ref), 'date': ref['date'], 'projectId': ref['projectId'],
                         'kind': 'manual', 'title': '手動追加の参考資料', 'text': ref['text'], 'url': ref['url']})
    old_manifest = read_json(dest / 'decisions.json', {'projects': []})
    old = {d['id']: d for d in old_manifest['projects']}
    _, previous = split_episodes(read_json(episode_path, legacy))
    overrides = read_json(ROOT / 'data/ntv/overrides.json', {})
    client = OpenAI(args.cache_dir / 'openai', offline=args.offline)
    reused = 0
    decisions, current_ids = [], set()
    eligible = [r for r in rows if r['date'] is None or args.since.isoformat() <= r['date'] <= args.today.isoformat()]
    # Detect reorder/removal/addition in articles seen in an earlier snapshot.
    changed_articles = set()
    for article in {r['articleId'] for r in eligible}:
        before = {k: project_key(v['project']) for k, v in old.items() if k.split(':')[0] == article}
        after = {r['id']: project_key(r['project']) for r in eligible if r['articleId'] == article}
        if before and before != after:
            changed_articles.add(article)
    for row in eligible:
        key = row['id']
        current_ids.add(key)
        manual = overrides.get(key)
        if row['articleId'] in changed_articles and not (manual and manual.get('allowIdentityChange')):
            d = {'id': key, 'date': row['date'], 'project': row['project'], 'performers': row['performers'],
                 'source': row['source'], 'status': 'pending', 'reason': 'article_structure_changed', 'method': 'none', 'countries': [],
                 'observedProject': row['project']}
            # Preserve the old identity to keep this hold sticky until explicit review.
            if key in old:
                d['project'] = old[key]['project']
        else:
            d = decide(row, docs, client, manual, old.get(key))
            if old.get(key) == d and d['status'] in ('accepted', 'excluded'):
                reused += 1
        decisions.append(d)
    for doc in docs:
        if doc['kind'] != 'summary' or not args.since.isoformat() <= doc['date'] <= args.today.isoformat():
            continue
        key = 'summary:' + doc['id']
        current_ids.add(key)
        d = decide_summary(doc, eligible, client, args.since, args.today, old.get(key))
        if old.get(key, {}).get('inputHash') == d['inputHash'] and 'answer' in old.get(key, {}):
            reused += 1
        decisions.append(d)
    for key, d in old.items():
        if key not in current_ids:
            d = dict(d, status='pending', reason='source_missing_or_outside_window')
            decisions.append(d)
    reconcile(decisions)
    decisions.sort(key=lambda d: (d['date'] or '9999-12-31', d['id']))
    gaps = [d for d in decisions if d.get('sourceKind') == 'summary' and d['status'] == 'pending']
    episodes = make_episodes(decisions, previous, overrides)
    validate(episodes)
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != initial_hash:
        raise ValueError('既存データが実行中に変更されました')
    manifest = {'schemaVersion': 3, 'projects': decisions}
    markdown = report(decisions, gaps, warnings)
    # Prepare all data before replacing output files. A failed validation never publishes data.
    write_json(episode_path, legacy + episodes)
    write_json(dest / 'decisions.json', manifest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'report.md').write_text(markdown)
    stats = {'apiRequests': client.calls, 'cacheHits': client.hits, 'unchangedProjects': reused, 'usage': client.usage,
             'episodeRecords': len(episodes), 'totalEpisodeRecords': len(legacy) + len(episodes), 'projects': len(decisions), 'warnings': warnings}
    write_json(args.cache_dir / 'run.json', stats)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('更新中止: ' + str(error), file=sys.stderr)
        sys.exit(1)
