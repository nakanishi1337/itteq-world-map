import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from broadcasts.common import ROOT, read_json
spec=importlib.util.spec_from_file_location('updater',ROOT/'scripts/update-ntv.py')
updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)

class UpdateWindowTests(unittest.TestCase):
    def test_calendar_month_boundary(self):
        for date,expected in [('2026-09-30','2026-08-30'),('2026-03-31','2026-02-28'),('2024-03-31','2024-02-29'),('2026-01-15','2025-12-15')]:
            self.assertEqual(updater.month_before(dt.date.fromisoformat(date)).isoformat(),expected)

    def test_summary_distinguishes_actual_calls_cache_and_unchanged(self):
        runs=[]
        for date,mode,calls,status in [('2026-09-06','ai',1,'accepted'),('2026-09-13','unchanged',0,'accepted'),('2026-09-20','cache',0,'accepted'),('2026-09-27','ai',1,'pending')]:
            runs.append({'date':date,'mode':mode,'apiRequests':calls,'trigger':'未処理','decision':{'status':status,'reason':'openai_http_429' if status=='pending' else 'openai_projects','projects':[{'project':'古い企画' if status=='pending' else '取得企画'}]}})
        report=updater.run_report(dt.date(2026,8,30),dt.date(2026,9,30),runs,SimpleNamespace(calls=2,usage={}),[])
        self.assertIn('AI呼び出し: **2回**',report)
        self.assertIn('変更なし: 2026-09-13',report)
        self.assertIn('保存済みAPI回答: 2026-09-20',report)
        self.assertNotIn('古い企画',report)
        self.assertIn('以前のデータを保持',report)

    def test_only_window_is_extracted_and_old_records_remain(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);out=folder/'out';out.mkdir()
            articles=[]
            for i,date in enumerate(['2026-08-29','2026-08-30','2026-09-30','2026-10-01']):
                articles.append({'item_id':str(i),'content_id':304,'display_date':date,'data':{'title':'旅','tags':[{'text':'OAまとめ'}],'body':'本文'}})
            source=folder/'articles.json';source.write_text(json.dumps(articles))
            original=read_json(ROOT/'src/data/episodes.json')
            (out/'episodes.json').write_text(json.dumps(original))
            def extract(client,material,*args):
                client.calls+=1
                return {'projects':[]}
            argv=['update','--input',str(source),'--offline','--today','2026-09-30','--output-dir',str(out),'--cache-dir',str(folder/'cache')]
            with patch('sys.argv',argv),patch('builtins.print'),patch('broadcasts.openai.OpenAI.extract',autospec=True,side_effect=extract) as api:
                updater.main()
                self.assertEqual([c.args[1]['broadcastDate'] for c in api.call_args_list],['2026-08-30','2026-09-30'])
                self.assertEqual(read_json(out/'episodes.json'),original)
                updater.main()
                self.assertEqual(api.call_count,2)
            stats=read_json(folder/'cache/run.json')
            self.assertEqual(stats['apiRequests'],0)
            self.assertEqual(stats['unchangedBroadcasts'],2)
            self.assertIn('今回AIへのリクエストはありません',(folder/'cache/run.md').read_text())
