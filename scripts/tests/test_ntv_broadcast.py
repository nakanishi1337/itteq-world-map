import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ntv.common import ROOT, LEGACY_COUNT, read_json, split_episodes
from ntv.sources import articles_documents, parse_schedule
from ntv.pipeline import decide, make_episodes, validate_answer
from ntv.openai import OpenAI, OpenAIUnavailable, output

DOC={'date':'2026-09-27','title':'企画','text':'本文','kind':'summary','url':'https://www.ntv.co.jp/q/articles/example.html'}
ANSWER={'projects':[{'project':'企画','performers':['A','B'],'countries':['FR','GB'],'sourceUrls':[DOC['url']]}]}

class BroadcastTests(unittest.TestCase):
    def test_sources_allow_summary_only_and_preview_without_cast_or_headings(self):
        docs=articles_documents(read_json(ROOT/'scripts/tests/fixtures/ntv-articles.json'))
        self.assertTrue(any(d['kind']=='summary' for d in docs))
        article={'item_id':'a','content_id':304,'display_date':'2026-09-27 20:54:00','data':{'title':'旅','tags':[{'text':'OAまとめ'}],'body':'本文'}}
        self.assertEqual(articles_documents([article])[0]['date'],'2026-09-27')
        article['data']['title']='10月4日の「イッテQ」は'
        self.assertEqual(articles_documents([article])[0]['date'],'2026-10-04')
        with self.assertRaises(ValueError): articles_documents([])

    def test_reuse_changes_failure_empty_and_date_replacement(self):
        client=Mock();client.extract.return_value=ANSWER
        first=decide(DOC['date'],[DOC],client)
        episodes=make_episodes([first],[])
        self.assertIs(decide(DOC['date'],[DOC],client,first),first)
        self.assertEqual(client.extract.call_count,1)
        changed=dict(DOC,text='変更')
        client.extract.side_effect=OpenAIUnavailable('openai_http_429')
        failed=decide(DOC['date'],[changed],client,first)
        self.assertEqual(make_episodes([failed],episodes),episodes)
        client.extract.side_effect=None;client.extract.return_value={'projects':[]}
        empty=decide(DOC['date'],[changed],client,failed)
        self.assertEqual(make_episodes([empty],episodes),[])
        self.assertIs(decide(DOC['date'],[changed],client,empty),empty)
        renamed=copy.deepcopy(first);renamed['projects'][0]['project']='改題'
        replacement=make_episodes([renamed],episodes)
        self.assertEqual(len(replacement),2)
        self.assertTrue(all(e['project']=='改題' for e in replacement))
        self.assertEqual(make_episodes([],episodes),episodes)

    def test_new_document_refresh_and_missing_document_retained(self):
        client=Mock();client.extract.return_value=ANSWER
        first=decide(DOC['date'],[DOC],client)
        extra=dict(DOC,url=DOC['url']+'2',kind='preview')
        second=decide(DOC['date'],[DOC,extra],client,first)
        self.assertEqual(client.extract.call_count,2)
        self.assertIs(decide(DOC['date'],[extra],client,second),second)

    def test_json_validation(self):
        self.assertEqual(validate_answer(ANSWER,[DOC]),ANSWER)
        for key,value in [('countries',['ZZ']),('performers',[]),('sourceUrls',['https://bad.test'])]:
            bad=copy.deepcopy(ANSWER);bad['projects'][0][key]=value
            with self.assertRaises(OpenAIUnavailable):validate_answer(bad,[DOC])
        with self.assertRaises(OpenAIUnavailable):output({'status':'incomplete'},lambda v:v)
        with self.assertRaises(OpenAIUnavailable):output({'status':'completed','output':[{'content':[{'type':'refusal'}]}]},lambda v:v)

    def test_cache_and_failed_requests_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            client=OpenAI(Path(temp));response={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(ANSWER)}]}],'usage':{'input_tokens':100,'output_tokens':20}}
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test'}),patch('ntv.openai.request',return_value=json.dumps(response)) as request:
                first=decide(DOC['date'],[DOC],client)
                client.offline=True
                self.assertEqual(decide(DOC['date'],[DOC],client),first)
                self.assertEqual(request.call_count,1)
                self.assertEqual(client.usage['input_tokens'],100)
            client.offline=False
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test'}),patch('ntv.openai.request',side_effect=OSError('offline')) as request:
                for _ in range(2):self.assertEqual(decide(DOC['date'],[dict(DOC,text='changed')],client)['status'],'pending')
                self.assertEqual(request.call_count,2)

    def test_original_data_and_schedule(self):
        data=read_json(ROOT/'src/data/episodes.json');self.assertEqual(len(split_episodes(data)[0]),LEGACY_COUNT)
        bad=copy.deepcopy(data);bad[0]['project']='changed'
        with self.assertRaises(ValueError):split_episodes(bad)
        html=(ROOT/'scripts/tests/fixtures/nkt-20260215.html').read_text()
        self.assertIsNotNone(parse_schedule(html,'https://example.test','2026-02-15'))
        self.assertIsNone(parse_schedule(html,'https://example.test','2026-02-22'))

    def test_command_migrates_old_additions_only_on_success(self):
        spec=importlib.util.spec_from_file_location('updater',ROOT/'scripts/update-ntv.py')
        updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);out=folder/'out';out.mkdir()
            article={'item_id':'a','content_id':304,'display_date':'2026-09-27 20:54:00','data':{'title':'旅','tags':[{'text':'OAまとめ'}],'body':'本文'}}
            source=folder/'source.json';source.write_text(json.dumps([article]))
            original=read_json(ROOT/'src/data/episodes.json')
            (out/'episodes.json').write_text(json.dumps(original))
            args=['update','--input',str(source),'--offline','--today','2026-09-30','--output-dir',str(out),'--cache-dir',str(folder/'cache')]
            with patch('sys.argv',args),patch('builtins.print'):
                updater.main()
                self.assertEqual(read_json(out/'episodes.json'),original)
                with patch('ntv.openai.OpenAI.extract',return_value=ANSWER) as api:
                    updater.main();updater.main();self.assertEqual(api.call_count,1)
                result=read_json(out/'episodes.json')
                self.assertEqual(result[:LEGACY_COUNT],original[:LEGACY_COUNT])
                self.assertEqual(len([e for e in result[LEGACY_COUNT:] if e['date']=='2026-09-27']),2)
