#!/usr/bin/env python3
"""Run pinned Jev against reviewed Japanese examples. No key => explicitly unverified."""
import argparse
import json
import os
import sys
from pathlib import Path
from ntv.common import ROOT, read_json, write_json
from ntv.jev import Jev
from ntv.pipeline import decide, policy_hash
from ntv.sources import previews, summaries, parse_schedule


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache-dir', type=Path, default=ROOT / '.cache/ntv/evaluation')
    p.add_argument('--output', type=Path, default=ROOT / '.cache/ntv/evaluation-report.json')
    p.add_argument('--certify', action='store_true', help='成功時のみCI用評価証明を保存。不成功時は無効化')
    a = p.parse_args()
    if not os.environ.get('TYPESAFE_API_KEY'):
        print('UNVERIFIED: TYPESAFE_API_KEY is not set. Live evaluation was not run.', file=sys.stderr)
        return 2
    fixture = ROOT / 'scripts/tests/fixtures'
    articles = read_json(fixture / 'ntv-evaluation-articles.json')
    rows = {r['id']: r for r in previews(articles)}
    # Labels concern the supplied preview; the missing Finland case explicitly includes supporting sources.
    supplements = [d for d in summaries(articles) if d['date'] == '2026-02-15']
    supplements.append(parse_schedule((fixture / 'nkt-20260215.html').read_text(), 'https://www.nkt-tv.co.jp/program/detail.php?date=260215&no=22', '2026-02-15'))
    client = Jev(a.cache_dir, limit=200)
    outcomes = []
    for gold in read_json(fixture / 'ntv-gold.json'):
        d = decide(rows[gold['id']], supplements, client, gate=True)
        predicted = sorted(c['countryCode'] for c in d['countries']) if d['status'] == 'accepted' else []
        outcomes.append({'id': gold['id'], 'split': gold['split'], 'expected': gold['countries'],
                         'predicted': predicted, 'status': d['status'], 'reason': d['reason'], 'decision': d})
    metrics = {}
    for split in ('development', 'holdout'):
        subset = [o for o in outcomes if o['split'] == split]
        tp = sum(len(set(o['predicted']) & set(o['expected'])) for o in subset)
        fp = sum(len(set(o['predicted']) - set(o['expected'])) for o in subset)
        fn = sum(len(set(o['expected']) - set(o['predicted'])) for o in subset)
        metrics[split] = {'projects': len(subset), 'truePositives': tp, 'falsePositives': fp, 'falseNegatives': fn,
                          'precision': tp/(tp+fp) if tp+fp else None, 'recall': tp/(tp+fn) if tp+fn else None,
                          'pendingRate': sum(o['status']=='pending' for o in subset)/len(subset)}
    finland = next(o for o in outcomes if o['id'].startswith('xb8d5pluwyejoiic:'))
    # No vacuous pass when every model answer abstains. Require supported Jev decisions and the Finland supplement.
    passed = all(m['falsePositives'] == 0 for m in metrics.values()) and finland['predicted'] == ['FI'] and any(o['decision']['method']=='jev' and o['status']=='accepted' for o in outcomes)
    result = {'passed': passed, 'policyHash': policy_hash(), 'metrics': metrics,
              'apiRequests': client.calls, 'cacheHits': client.hits, 'usage': client.usage, 'outcomes': outcomes}
    write_json(a.output, result)
    if a.certify:
        write_json(ROOT / 'data/ntv/evaluation.json', {k: result[k] for k in ('passed','policyHash','metrics')})
    print(json.dumps({k:v for k,v in result.items() if k!='outcomes'}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
