import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ntv.common import ROOT, digest, read_json, write_json
from ntv.geography import candidates, heading_places, CITIES
from ntv.jev import Jev, JevUnavailable, MODEL
from ntv.pipeline import decide, judge, make_episodes, policy_hash
from ntv.sources import cast, parse_schedule, previews, summaries, Text

FIXTURES = Path(__file__).parent / 'fixtures'
ARTICLES = read_json(FIXTURES / 'ntv-evaluation-articles.json')
ROWS = {r['id']: r for r in previews(ARTICLES)}


def answer(value, choices, confidence=.99):
    return {'choice': value, 'confidence': confidence,
            'probabilities': {k: (1.0 if k == value else 0.0) for k in choices}}


class FakeJev:
    """Models the interface, not language understanding; live evaluation is separate."""
    def __init__(self, visits=('FI',), low=False):
        self.visits = visits
        self.low = low
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        result = {}
        for k, q in questions.items():
            if k == 'kind': value = 'visit'
            elif k == 'match': value = 'same'
            elif k.startswith('country_'): value = 'visit' if k[8:] in self.visits else 'other'
            elif k.startswith('evidence_'):
                value = next((c for c in q['criteria'] if c != 'none'), 'none') if k[9:] in self.visits else 'none'
            else: raise AssertionError(k)
            result[k] = answer(value, q['criteria'], .3 if self.low else .99)
        return result


def row_start(prefix):
    return next(copy.deepcopy(r) for key, r in ROWS.items() if key.startswith(prefix))


class GeographyTests(unittest.TestCase):
    def test_regions_and_prefectures(self):
        for place, code in [('ハワイ','US'),('アラスカ','US'),('ドバイ','AE'),('山梨','JP'),('北海道','JP'),('東京都','JP')]:
            self.assertEqual(heading_places('企画 in '+place)[0]['countryCode'], code)

    def test_many_cities_and_ambiguity(self):
        self.assertGreater(CITIES['cityCount'], 30000)
        for place, code in [('ケアンズ','AU'),('フィレンツェ','IT'),('ヘルシンキ','FI'),('アンカレッジ','US')]:
            self.assertIn(code, [r['countryCode'] for r in candidates(place)])
        self.assertEqual(heading_places('企画 in バンクーバー'), [])
        self.assertEqual(heading_places('企画 in ロンドン'), [])
        self.assertTrue({'CA','US'}.issubset({r['countryCode'] for r in candidates('バンクーバー')}))

    def test_complete_heading_only(self):
        self.assertEqual([p['countryCode'] for p in heading_places('企画 in フランス・オーストリア')], ['FR','AT'])
        for s in ['企画 in 未知島', '企画 in タイ・未知島', '企画 in タイで大冒険', '企画 in タイ・']:
            self.assertEqual(heading_places(s), [])

    def test_substrings_not_countries(self):
        for text, forbidden in [('タイム','TH'),('富士急ハイランド','IR'),('カリビアン','LY'),('日本テレビ','JP')]:
            self.assertNotIn(forbidden, {r['countryCode'] for r in candidates(text)})


class SourceTests(unittest.TestCase):
    def test_cast_continuation_and_guest(self):
        text = '出演者：A（B・C）、\nD・E\n本文\nスペシャルゲスト：Kōki,\nスタジオ出演者：F'
        self.assertEqual(cast(text), ['A（B・C）','D','E','Kōki,'])

    def test_schedule_validation(self):
        html = (FIXTURES / 'nkt-20260215.html').read_text()
        self.assertEqual(parse_schedule(html,'https://example.test','2026-02-15')['date'], '2026-02-15')
        self.assertIsNone(parse_schedule(html,'https://example.test','2026-02-22'))
        self.assertIsNone(parse_schedule(html.replace('19時58分','09時58分'),'https://example.test'))
        parser = Text()
        parser.feed("<a href='detail.php?date=260215&no=999'><div>イッテQ!</div></a>")
        self.assertEqual(parser.links[0][0], 'detail.php?date=260215&no=999')


class DecisionTests(unittest.TestCase):
    def test_six_regressions_heading(self):
        fake = FakeJev()
        for prefix, code in [('6719w74y1wf4vthg:2','VN'),('gdlmgvmkox3looo0:1','KR'),('gdlmgvmkox3looo0:2','JP')]:
            d = decide(row_start(prefix), [], fake, False)
            self.assertEqual([c['countryCode'] for c in d['countries']], [code])
            self.assertEqual(d['status'],'accepted')
        self.assertEqual(fake.calls, 0)

    def test_jev_evidence_and_gate(self):
        row = row_start('xb8d5pluwyejoiic:')
        docs = [d for d in summaries(ARTICLES) if d['date']==row['date']]
        d = decide(row, docs, FakeJev(), True)
        self.assertEqual(d['status'], 'accepted')
        self.assertEqual([c['countryCode'] for c in d['countries']], ['FI'])
        self.assertIn('フィンランド', d['countries'][0]['evidence']['text'])
        self.assertEqual(decide(row, docs, FakeJev(), False)['reason'], 'live_evaluation_not_passed')
        self.assertEqual(decide(row, docs, FakeJev(low=True), True)['status'], 'pending')
        self.assertEqual(decide(row, [], FakeJev(visits=()), True)['status'], 'pending')

    def test_past_and_neighbor_and_exhibit_exclusion_contract(self):
        for prefix, expected in [('nrqxi8sr20r3i6nj:1','NL'),('oyk5obouu2jkjmf4:1','ZW'),('r5nu7sivq6100j2s:1','GB')]:
            r = row_start(prefix)
            d = decide(r, [], FakeJev(visits=(expected,)), True)
            self.assertEqual([c['countryCode'] for c in d['countries']], [expected])
            self.assertEqual(d['status'],'accepted')

    def test_recap_and_missing_cast(self):
        fake = FakeJev()
        row = row_start('xb8d5pluwyejoiic:')
        row['project'] = '真夏の爆笑アワード'
        self.assertEqual(decide(row, [], fake, True)['status'], 'excluded')
        row['performers'] = []
        self.assertEqual(decide(row, [], fake, True)['status'], 'pending')
        self.assertEqual(fake.calls, 0)

    def test_all_cast_each_country_and_preserve_on_failure(self):
        row = row_start('6719w74y1wf4vthg:1')
        row['performers'] = ['A','B']
        d = decide(row, [], FakeJev(), False)
        episodes = make_episodes([d], [], {})
        self.assertEqual(len(episodes),2)
        self.assertTrue(all(e['performers']==['A','B'] for e in episodes))
        self.assertEqual(make_episodes([d], episodes, {}), episodes)
        self.assertEqual(make_episodes([dict(d,status='pending')], episodes, {}), episodes)
        self.assertEqual(make_episodes([], episodes, {}), episodes)
        self.assertEqual(make_episodes([dict(d,status='excluded')], episodes, {d['id']:{'status':'excluded'}}), [])

    def test_manual_override(self):
        row = row_start('xb8d5pluwyejoiic:')
        d = decide(row, [], FakeJev(), False, {'status':'accepted','countries':['FI'],'evidence':{'text':'フィンランド','url':row['source']}})
        self.assertEqual(d['status'], 'accepted')
        self.assertEqual(d['method'], 'manual')


class ApiTests(unittest.TestCase):
    def test_cache_limits_missing_key_and_validation(self):
        questions = {'match': {'type':'choice','instructions':'test','criteria':{'yes':None,'no':None}}}
        response = {'model':MODEL,'answers':{'match':answer('yes',questions['match']['criteria'])},'usage':{'input_tokens':1}}
        with tempfile.TemporaryDirectory() as temp:
            client = Jev(Path(temp))
            with patch.dict(os.environ, {'TYPESAFE_API_KEY':'test'}), patch('ntv.jev.request', return_value=json.dumps(response)) as req:
                self.assertEqual(client.ask('text',questions),response['answers'])
                client.ask('text',questions)
                self.assertEqual(req.call_count,1)
                self.assertEqual(client.hits,1)
                client.limit=1
                with self.assertRaises(JevUnavailable): client.ask('new',questions)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(JevUnavailable): client.ask('new',questions)
            broken=copy.deepcopy(response); broken['answers']['match']['choice']='invented'
            with self.assertRaises(JevUnavailable): Jev.validate(broken, questions)


class CommandTests(unittest.TestCase):
    def test_offline_idempotency_and_failure_preserves_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output=folder/'out'; cache=folder/'cache'
            cmd=[sys.executable,str(ROOT/'scripts/update-ntv.py'),'--input',str(FIXTURES/'ntv-evaluation-articles.json'),'--offline','--since','2026-01-01','--today','2026-09-29','--output-dir',str(output),'--cache-dir',str(cache)]
            env={k:v for k,v in os.environ.items() if k!='TYPESAFE_API_KEY'}
            subprocess.run(cmd,check=True,capture_output=True,env=env)
            first={p.name:p.read_bytes() for p in output.iterdir()}
            subprocess.run(cmd,check=True,capture_output=True,env=env)
            self.assertEqual(first,{p.name:p.read_bytes() for p in output.iterdir()})
            bad=folder/'bad.json'; bad.write_text('[]')
            cmd[cmd.index('--input')+1]=str(bad)
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,env=env).returncode,0)
            self.assertEqual(first,{p.name:p.read_bytes() for p in output.iterdir()})


class FailureAndIdentityTests(unittest.TestCase):
    def test_retry_policy(self):
        import urllib.error
        from ntv.common import request
        error = urllib.error.HTTPError('https://example.test', 529, 'Overloaded', {}, None)
        with patch('ntv.common.urllib.request.urlopen', side_effect=error) as call, patch('ntv.common.time.sleep'):
            with self.assertRaises(urllib.error.HTTPError): request('https://example.test')
            self.assertEqual(call.call_count, 3)
        error = urllib.error.HTTPError('https://example.test', 401, 'Unauthorized', {}, None)
        with patch('ntv.common.urllib.request.urlopen', side_effect=error) as call:
            with self.assertRaises(urllib.error.HTTPError): request('https://example.test')
            self.assertEqual(call.call_count, 1)

    def test_reorder_hold_future_and_prior_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output=folder/'out'; source=folder/'articles.json'
            original=copy.deepcopy(next(a for a in ARTICLES if a['item_id']=='6719w74y1wf4vthg'))
            write_json(source, [original])
            cmd=[sys.executable,str(ROOT/'scripts/update-ntv.py'),'--input',str(source),'--offline','--since','2026-01-01','--today','2026-01-17','--output-dir',str(output),'--cache-dir',str(folder/'cache')]
            env={k:v for k,v in os.environ.items() if k!='TYPESAFE_API_KEY'}
            subprocess.run(cmd,check=True,capture_output=True,env=env)
            self.assertEqual(read_json(output/'episodes-ntv.json'), [])
            cmd[cmd.index('--today')+1]='2026-01-19'
            subprocess.run(cmd,check=True,capture_output=True,env=env)
            first=read_json(output/'episodes-ntv.json')
            self.assertEqual(len(first),3)
            original['data']['body']=original['data']['body'].replace('ロッチ中岡のQtube','中岡の変更企画')
            write_json(source,[original])
            for _ in range(2):
                subprocess.run(cmd,check=True,capture_output=True,env=env)
                self.assertEqual(read_json(output/'episodes-ntv.json'),first)
                self.assertTrue(all(d['reason']=='article_structure_changed' for d in read_json(output/'decisions.json')['projects']))

    def test_no_key_evaluation_is_explicitly_unverified(self):
        env={k:v for k,v in os.environ.items() if k!='TYPESAFE_API_KEY'}
        result=subprocess.run([sys.executable,str(ROOT/'scripts/evaluate-ntv.py')],capture_output=True,text=True,env=env)
        self.assertEqual(result.returncode,2)
        self.assertIn('UNVERIFIED',result.stderr)


if __name__ == '__main__':
    unittest.main()
