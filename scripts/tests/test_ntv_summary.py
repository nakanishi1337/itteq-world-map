import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ntv.summary import decide_summary, reconcile, validate
from ntv.pipeline import make_episodes
from ntv.openai import OpenAI, OpenAIUnavailable

DOC = {'id': 'oa1', 'date': '2026-09-27', 'title': '世界遺産駅伝', 'text': 'ロケ本文', 'url': 'https://www.ntv.co.jp/q/articles/304oa1.html', 'kind': 'summary'}
ANSWER = {'broadcastDate': '2026-09-27', 'matchedPreviewId': None, 'visits': [
    {'countryCode': 'GB', 'performers': ['A']}, {'countryCode': 'CZ', 'performers': ['B']}]}
SINCE, TODAY = dt.date(2026,7,27), dt.date(2026,9,30)

class SummaryTests(unittest.TestCase):
    def decide(self, client, previous=None, rows=None, doc=None):
        return decide_summary(doc or DOC, rows or [], client, SINCE, TODAY, previous)

    def test_cast_per_country_persistence_and_changed_source(self):
        client = Mock(); client.extract.return_value = ANSWER
        first = self.decide(client)
        records = make_episodes([first], [], {})
        self.assertEqual({e['countryCode']:e['performers'] for e in records}, {'GB':['A'], 'CZ':['B']})
        self.assertEqual(self.decide(client, first), first)
        self.assertEqual(client.extract.call_count, 1)
        changed = self.decide(client, first, doc=dict(DOC,text='変更'))
        self.assertEqual(client.extract.call_count, 2)
        client.extract.side_effect = OpenAIUnavailable('openai_http_429')
        failed = self.decide(client, changed, doc=dict(DOC,text='さらに変更'))
        self.assertEqual(make_episodes([failed], records, {}), records)

    def test_empty_and_future(self):
        client=Mock(); client.extract.return_value=dict(ANSWER,visits=[])
        d=self.decide(client)
        self.assertEqual(d['status'],'accepted')
        self.decide(client,d); self.assertEqual(client.extract.call_count,1)
        client.extract.return_value=dict(ANSWER,broadcastDate='2026-10-04')
        self.assertEqual(self.decide(client)['reason'],'outside_window')

    def test_late_preview_and_same_day_other_project(self):
        client=Mock(); client.extract.return_value=ANSWER
        first=self.decide(client)
        preview={'id':'preview:1','date':DOC['date'],'project':'駅伝','body':'予告本文',
                 'status':'accepted','countries':[], 'performers':[], 'source':DOC['url']}
        client.extract.return_value=dict(ANSWER,matchedPreviewId=preview['id'])
        summary=self.decide(client, first, [preview])
        reconcile([preview,summary])
        self.assertEqual(summary['reason'],'covered_by_preview')
        self.assertEqual(make_episodes([summary],make_episodes([first],[],{}),{}),[])
        self.assertEqual(client.extract.call_count,2)
        client.extract.return_value=ANSWER
        other=self.decide(client, rows=[preview])
        reconcile([preview,other]); self.assertEqual(other['status'],'accepted')

    def test_failed_preview_uses_summary_without_poisoning_preview_status(self):
        client=Mock(); client.extract.return_value=dict(ANSWER,matchedPreviewId='p:1')
        preview={'id':'p:1','date':DOC['date'],'project':'駅伝','body':'予告', 'status':'pending'}
        summary=self.decide(client, rows=[preview]); reconcile([preview,summary])
        self.assertEqual(preview['status'],'pending')
        self.assertEqual(preview['supersededBy'],summary['id'])
        preview['status']='accepted'; reconcile([preview,summary])
        self.assertNotIn('supersededBy',preview)
        self.assertEqual(summary['status'],'excluded')

    def test_shape_and_cache(self):
        for bad in [dict(ANSWER,broadcastDate='bad'),dict(ANSWER,matchedPreviewId='missing'),dict(ANSWER,visits=[{'countryCode':'GB','performers':[]}])]:
            with self.assertRaises(OpenAIUnavailable): validate(bad,[])
        with tempfile.TemporaryDirectory() as temp:
            client=OpenAI(Path(temp))
            response={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(ANSWER)}]}]}
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test'}),patch('ntv.openai.request',return_value=json.dumps(response)) as call:
                first=self.decide(client)
                client.offline=True
                self.assertEqual(self.decide(client),first)
                self.assertEqual(call.call_count,1)
