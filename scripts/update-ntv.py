#!/usr/bin/env python3
"""Collect official articles, resolve destinations, and prepare a reviewable data snapshot."""
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
    lines = ['# 日テレ放送データの更新候補', '',
             f"企画: 採用 {counts['accepted']} / 保留 {counts['pending']} / 除外 {counts['excluded']}",
             f"見出し確定 {sum(d['status']=='accepted' and d['method']=='heading' for d in decisions)} / OpenAI確定 {sum(d['status']=='accepted' and d['method']=='openai' for d in decisions)}", '',
             '出演者は日テレの企画欄を使用し、採用した各国に全員を紐付けます。', '',
             '| 放送日 | 企画 | 判定 | 国 | 根拠・保留理由 |', '|---|---|---|---|---|']
    for d in decisions:
        title = d['project'].replace('|', '／').replace('\n', ' ')
        countries = ', '.join(c['countryCode'] for c in d['countries']) or '—'
        links = ' '.join(f"[根拠]({u})" for u in sorted({c['evidence']['url'] for c in d['countries']}))
        lines.append(f"| {d['date']} | [{title}]({d['source']}) | {d['status']} | {countries} | {d['reason']} {links} |")
    if gaps:
        lines += ['', '## 予告が見つからない放送・記事', '']
        lines += [f"- {g['date']}: [{g['title']}]({g['url']})（出演者を推測せず保留）" for g in gaps]
    if warnings:
        lines += ['', '## 取得上の注意', ''] + ['- ' + w for w in sorted(set(warnings))]
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path)
    p.add_argument('--since', type=dt.date.fromisoformat, default=dt.date(2026, 7, 27))
    p.add_argument('--today', type=dt.date.fromisoformat, default=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date())
    p.add_argument('--cache-dir', type=Path, default=ROOT / '.cache/ntv')
    p.add_argument('--output-dir', type=Path, help='検証用出力先。省略時はリポジトリの更新候補を生成')
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
        schedule_docs = schedules(args.cache_dir, warnings, args.today, references)
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
    for key, d in old.items():
        if key not in current_ids:
            d = dict(d, status='pending', reason='source_missing_or_outside_window')
            decisions.append(d)
    decisions.sort(key=lambda d: (d['date'] or '9999-12-31', d['id']))
    known_dates = {r['date'] for r in rows}
    gaps = sorted([d for d in docs if d['date'] not in known_dates and args.since.isoformat() <= d['date'] <= args.today.isoformat()], key=lambda d: (d['date'], d['url']))
    episodes = make_episodes(decisions, previous, overrides)
    validate(episodes)
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != initial_hash:
        raise ValueError('既存データが実行中に変更されました')
    manifest = {'schemaVersion': 2, 'projects': decisions, 'missingPreviews': gaps}
    markdown = report(decisions, gaps, warnings)
    # Prepare all data before replacing output files. A failed CI never publishes a PR.
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
