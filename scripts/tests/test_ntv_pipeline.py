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
from ntv.common import ROOT, LEGACY_COUNT, split_episodes, read_json, write_json
from ntv.geography import heading_places, CITIES
from ntv.openai import OpenAI, OpenAIUnavailable, output, validate
from ntv.pipeline import decide, make_episodes
from ntv.sources import cast, parse_schedule, previews, summaries, Text

FIXTURES = Path(__file__).parent / 'fixtures'
ARTICLES = read_json(FIXTURES / 'ntv-articles.json')
ROWS = {r['id']: r for r in previews(ARTICLES)}


def row_start(prefix):
    return next(copy.deepcopy(r) for key, r in ROWS.items() if key.startswith(prefix))


class FakeOpenAI:
    """Tests processing and persistence, without pretending to verify country accuracy."""
    def __init__(self, codes=('FI',), error=None):
        self.codes, self.error, self.calls, self.docs = list(codes), error, 0, []

    def countries(self, row, docs):
        self.calls += 1
        self.docs = docs
        if self.error:
            raise OpenAIUnavailable(self.error)
        return self.codes


class GeographyTests(unittest.TestCase):
    def test_regions_and_prefectures(self):
        for place, code in [('ハワイ','US'),('アラスカ','US'),('ドバイ','AE'),('山梨','JP'),('北海道','JP'),('東京都','JP')]:
            self.assertEqual(heading_places('企画 in '+place)[0]['countryCode'], code)

    def test_city_dictionary_and_ambiguity(self):
        self.assertGreater(CITIES['cityCount'], 30000)
        self.assertEqual(heading_places('企画 in ヘルシンキ')[0]['countryCode'], 'FI')
        for place in ('バンクーバー', 'ロンドン', '未知島'):
            self.assertEqual(heading_places('企画 in '+place), [])

    def test_complete_heading_only(self):
        self.assertEqual([p['countryCode'] for p in heading_places('企画 in フランス・オーストリア')], ['FR','AT'])
        for s in ['企画 in 未知島', '企画 in タイ・未知島', '企画 in タイで大冒険', '企画 in タイ・']:
            self.assertEqual(heading_places(s), [])


class SharedDataTests(unittest.TestCase):
    def test_legacy_preserved_and_changes_rejected(self):
        data = read_json(ROOT / 'src/data/episodes.json')
        legacy, additions = split_episodes(data)
        self.assertEqual(len(legacy), LEGACY_COUNT)
        self.assertTrue(all(e['projectId'] for e in additions))
        changed = copy.deepcopy(data)
        changed[0]['project'] += '変更'
        with self.assertRaises(ValueError): split_episodes(changed)
        with self.assertRaises(ValueError): split_episodes(data[1:])


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
    def test_static_headings_skip_api(self):
        client = FakeOpenAI()
        for prefix, code in [('6719w74y1wf4vthg:2','VN'),('gdlmgvmkox3looo0:1','KR'),('gdlmgvmkox3looo0:2','JP')]:
            d = decide(row_start(prefix), [], client)
            self.assertEqual([c['countryCode'] for c in d['countries']], [code])
            self.assertEqual(d['status'],'accepted')
        self.assertEqual(client.calls, 0)

    def test_finland_candidate_material_in_single_call(self):
        row = row_start('xb8d5pluwyejoiic:')
        client = FakeOpenAI()
        d = decide(row, summaries(ARTICLES), client)
        self.assertEqual(d['status'], 'accepted')
        self.assertEqual([c['countryCode'] for c in d['countries']], ['FI'])
        self.assertEqual(client.calls, 1)
        self.assertTrue(any('フィンランド' in doc['text'] for doc in client.docs))
        self.assertTrue(all(doc.get('date', row['date']) == row['date'] for doc in client.docs))
        self.assertTrue(any(doc['kind'] == 'summary' for doc in client.docs))

    def test_empty_is_processed_and_reused_without_artifact(self):
        row = row_start('xb8d5pluwyejoiic:')
        client = FakeOpenAI(codes=())
        d = decide(row, [], client)
        self.assertEqual(d['status'], 'accepted')
        self.assertEqual(d['countries'], [])
        self.assertEqual(decide(row, [], client, previous=d), d)
        self.assertEqual(client.calls, 1)

    def test_changed_material_replaces_countries_failure_preserves_and_retries(self):
        row = row_start('xb8d5pluwyejoiic:')
        first = decide(row, [], FakeOpenAI(codes=('FR','CH','GB')))
        episodes = make_episodes([first], [], {})
        self.assertEqual(len(episodes), 3)
        row['body'] += '\n新しい本文'
        failed_client = FakeOpenAI(error='openai_http_429')
        failure = decide(row, [], failed_client, previous=first)
        self.assertEqual(make_episodes([failure], episodes, {}), episodes)
        decide(row, [], failed_client, previous=failure)
        self.assertEqual(failed_client.calls, 2)
        replacement = decide(row, [], FakeOpenAI(codes=('FI',)), previous=failure)
        self.assertEqual([e['countryCode'] for e in make_episodes([replacement], episodes, {})], ['FI'])
        empty = decide(row, [], FakeOpenAI(codes=()), previous=failure)
        self.assertEqual(make_episodes([empty], episodes, {}), [])

    def test_new_supplement_triggers_refresh_and_sources_recorded(self):
        row = row_start('xb8d5pluwyejoiic:')
        client = FakeOpenAI()
        previous = decide(row, [], client)
        docs = summaries(ARTICLES)
        latest = decide(row, docs, client, previous=previous)
        self.assertEqual(client.calls, 2)
        self.assertNotEqual(previous['inputHash'], latest['inputHash'])
        sources = make_episodes([latest], [], {})[0]['sources']
        self.assertGreater(len(sources), 1)
        self.assertEqual(decide(row, list(reversed(docs)), client, previous=latest), latest)
        self.assertEqual(client.calls, 2)

    def test_recap_missing_cast_and_manual(self):
        client = FakeOpenAI()
        row = row_start('xb8d5pluwyejoiic:')
        row['project'] = '真夏の爆笑アワード'
        self.assertEqual(decide(row, [], client)['status'], 'excluded')
        row['performers'] = []
        self.assertEqual(decide(row, [], client)['status'], 'pending')
        self.assertEqual(client.calls, 0)
        row = row_start('xb8d5pluwyejoiic:')
        d = decide(row, [], client, {'status':'accepted','countries':['FI'],'evidence':{'text':'フィンランド','url':row['source']}})
        self.assertEqual(d['method'], 'manual')
        self.assertEqual(client.calls, 0)

    def test_all_cast_each_country_and_preserve_missing_source(self):
        row = row_start('6719w74y1wf4vthg:1')
        row['performers'] = ['A','B']
        d = decide(row, [], FakeOpenAI())
        episodes = make_episodes([d], [], {})
        self.assertEqual(len(episodes),2)
        self.assertTrue(all(e['performers']==['A','B'] for e in episodes))
        self.assertEqual(make_episodes([], episodes, {}), episodes)
        self.assertEqual(make_episodes([dict(d,status='excluded')], episodes, {}), [])


class ApiTests(unittest.TestCase):
    def test_cache_structured_request_and_offline(self):
        response = {'status':'completed','output':[{'content':[{'type':'output_text','text':'{"countries":["FI","FI"]}'}]}], 'usage':{'input_tokens':1}}
        row = row_start('xb8d5pluwyejoiic:')
        with tempfile.TemporaryDirectory() as temp:
            client = OpenAI(Path(temp))
            with patch.dict(os.environ, {'OPENAI_API_KEY':'test'}), patch('ntv.openai.request', return_value=json.dumps(response)) as req:
                self.assertEqual(client.countries(row, []), ['FI'])
                payload = req.call_args.args[1]
                self.assertTrue(payload['text']['format']['strict'])
                self.assertFalse(payload['store'])
                client.countries(row, [])
                self.assertEqual(req.call_count,1)
                self.assertEqual(client.hits,1)
            offline = OpenAI(Path(temp), offline=True)
            with patch('ntv.openai.request', side_effect=AssertionError('offline network')):
                self.assertEqual(offline.countries(row, []), ['FI'])
                with self.assertRaisesRegex(OpenAIUnavailable,'offline_cache_miss'):
                    offline.countries(row, [{'text':'new'}])

    def test_failures_not_cached_and_no_key(self):
        row = row_start('xb8d5pluwyejoiic:')
        with tempfile.TemporaryDirectory() as temp:
            client = OpenAI(Path(temp))
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(OpenAIUnavailable, 'openai_api_key_missing'):
                    client.countries(row, [])
            with patch.dict(os.environ, {'OPENAI_API_KEY':'test'}), patch('ntv.openai.request', return_value='{"status":"incomplete"}') as req:
                for _ in range(2):
                    with self.assertRaises(OpenAIUnavailable): client.countries(row, [])
                self.assertEqual(req.call_count, 2)
                self.assertEqual(list(Path(temp).glob('*.json')), [])

    def test_shape_codes_refusal_and_incomplete(self):
        for value in ({'countries':['ZZ']}, {'countries':'FI'}, {'countries':[1]}, {'countries':['FI'],'extra':1}, []):
            with self.assertRaises(OpenAIUnavailable): validate(value)
        for response in ({'status':'incomplete'}, {'status':'completed','output':[{'content':[{'type':'refusal'}]}]}):
            with self.assertRaises(OpenAIUnavailable): output(response)

    def test_retry_policy(self):
        import urllib.error
        from ntv.common import request
        error = urllib.error.HTTPError('https://example.test', 429, 'Rate limited', {}, None)
        with patch('ntv.common.urllib.request.urlopen', side_effect=error) as call, patch('ntv.common.time.sleep'):
            with self.assertRaises(urllib.error.HTTPError): request('https://example.test')
            self.assertEqual(call.call_count, 3)


class CommandTests(unittest.TestCase):
    def test_updater_persists_answers_and_only_refreshes_changed_material(self):
        spec = importlib.util.spec_from_file_location('updater', ROOT / 'scripts/update-ntv.py')
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'articles.json'
            article = copy.deepcopy(next(a for a in ARTICLES if a['item_id'] == 'xb8d5pluwyejoiic'))
            write_json(source, [article])
            args = ['update-ntv', '--input', str(source), '--since', '2026-01-01',
                    '--today', '2026-09-30', '--output-dir', str(folder / 'out'), '--cache-dir', str(folder / 'cache')]
            with patch('sys.argv', args), patch.object(updater, 'schedules', return_value=[]), patch('ntv.openai.OpenAI.countries', return_value=['FI']) as api, patch('builtins.print'):
                updater.main()
                self.assertEqual(api.call_count, 1)
                updater.main()
                self.assertEqual(api.call_count, 1)
                article['data']['body'] += '<p>追記</p>'
                write_json(source, [article])
                api.return_value = ['SE']
                updater.main()
                self.assertEqual(api.call_count, 2)
                self.assertEqual([e['countryCode'] for e in read_json(folder / 'out/episodes.json')[LEGACY_COUNT:]], ['SE'])
                updater.main()
                self.assertEqual(api.call_count, 2)

    def test_offline_idempotency_and_failure_preserves_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output_dir=folder/'out'; cache=folder/'cache'
            cmd=[sys.executable,str(ROOT/'scripts/update-ntv.py'),'--input',str(FIXTURES/'ntv-articles.json'),'--offline','--since','2026-01-01','--today','2026-09-29','--output-dir',str(output_dir),'--cache-dir',str(cache)]
            subprocess.run(cmd,check=True,capture_output=True)
            first={p.name:p.read_bytes() for p in output_dir.iterdir()}
            subprocess.run(cmd,check=True,capture_output=True)
            self.assertEqual(first,{p.name:p.read_bytes() for p in output_dir.iterdir()})
            bad=folder/'bad.json'; bad.write_text('[]')
            cmd[cmd.index('--input')+1]=str(bad)
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
            self.assertEqual(first,{p.name:p.read_bytes() for p in output_dir.iterdir()})

    def test_reorder_hold_future_and_prior_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output_dir=folder/'out'; source=folder/'articles.json'
            original=copy.deepcopy(next(a for a in ARTICLES if a['item_id']=='6719w74y1wf4vthg'))
            write_json(source, [original])
            cmd=[sys.executable,str(ROOT/'scripts/update-ntv.py'),'--input',str(source),'--offline','--since','2026-01-01','--today','2026-01-17','--output-dir',str(output_dir),'--cache-dir',str(folder/'cache')]
            subprocess.run(cmd,check=True,capture_output=True)
            self.assertEqual(read_json(output_dir/'episodes.json'), read_json(ROOT/'src/data/episodes.json')[:LEGACY_COUNT])
            cmd[cmd.index('--today')+1]='2026-01-19'
            subprocess.run(cmd,check=True,capture_output=True)
            first=read_json(output_dir/'episodes.json')
            self.assertEqual(len(first),LEGACY_COUNT + 3)
            original['data']['body']=original['data']['body'].replace('ロッチ中岡のQtube','中岡の変更企画')
            write_json(source,[original])
            for _ in range(2):
                subprocess.run(cmd,check=True,capture_output=True)
                self.assertEqual(read_json(output_dir/'episodes.json'),first)
                self.assertTrue(all(d['reason']=='article_structure_changed' for d in read_json(output_dir/'decisions.json')['projects']))


if __name__ == '__main__':
    unittest.main()
