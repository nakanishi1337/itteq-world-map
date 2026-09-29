import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'collect-ntv-previews.py'
spec = importlib.util.spec_from_file_location('previews', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/ntv-previews.json').read_text())


class ExtractionTests(unittest.TestCase):
    def test_real_articles(self):
        result = m.collect(FIXTURE)
        self.assertEqual(len(result['records']), 5)
        rows = {r['articleId'] + ':' + str(r['projectIndex']): r for r in result['records']}
        q = rows['c6mxiawl9vbfzw3f:1']
        self.assertEqual(q['date'], '2026-09-20')
        self.assertEqual(q['performers'], ['中岡創一'])
        self.assertEqual([c['countryCode'] for c in q['countryCandidates']], ['FR', 'AT'])
        self.assertEqual([c['countryCode'] for c in rows['c6mxiawl9vbfzw3f:2']['countryCandidates']], ['TH'])
        relay = rows['o8j27r8ivv3apxgg:1']
        self.assertEqual(len(relay['performers']), 4)
        self.assertEqual([c['countryCode'] for c in relay['countryCandidates']], ['NA'])
        summer = rows['4hk8pk80ica7w563:1']
        self.assertEqual(len(summer['performers']), 3)
        self.assertEqual([c['countryCode'] for c in summer['countryCandidates']], ['CH', 'NL', 'GB'])
        for row in rows.values():
            self.assertNotIn('countryCode', row)
            for country in row['countryCandidates']:
                for evidence in country['evidence']:
                    self.assertEqual(row['evidenceText'][evidence['start']:evidence['end']], evidence['text'])

    def test_dates(self):
        self.assertEqual(m.broadcast_date('1月3日の「イッテQ」は', '2025-12-28 20:54:00'), '2026-01-03')
        self.assertIsNone(m.broadcast_date('2月30日の「イッテQ」は', '2026-02-20'))
        self.assertIsNone(m.broadcast_date('3月29日の「イッテQ」は', '2026-05-01'))

    def test_boundaries(self):
        self.assertEqual([c['countryCode'] for c in m.country_candidates('タイム オマーン マリ共和国 南アフリカ共和国 インドネシア')], ['OM', 'ML', 'ZA', 'ID'])
        self.assertEqual(m.country_candidates('北海道 ドバイ ハワイ'), [])
        self.assertEqual(m.split_cast('A（コンビ・名）、 B・C'), ['A（コンビ・名）', 'B', 'C'])

    def test_missing_and_html(self):
        articles = copy.deepcopy(FIXTURE[:1])
        articles[0]['data']['body'] = '<h2><strong>企画&amp;特別編</strong></h2><p>出演者：A・B<br>タイへ！&nbsp;</p><h2>国内</h2><p>北海道</p>'
        rows = m.collect(articles)['records']
        self.assertEqual(rows[0]['project'], '企画&特別編')
        self.assertEqual(rows[0]['performers'], ['A', 'B'])
        self.assertEqual(rows[1]['reviewReasons'], ['missing_performers', 'no_country_candidates'])
        articles[0]['data']['body'] = '<p>本文のみ</p>'
        result = m.collect(articles + FIXTURE[1:])
        self.assertIn('missing_headings', [i['reason'] for i in result['articleIssues']])

    def test_filter_and_determinism(self):
        unrelated = copy.deepcopy(FIXTURE[0])
        unrelated['data']['title'] = 'OAまとめ'
        result = m.collect(FIXTURE + [unrelated], '2026-09-01')
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(m.collect(FIXTURE), m.collect(list(reversed(FIXTURE))))
        with self.assertRaises(ValueError):
            m.collect([unrelated])
        with self.assertRaises(ValueError):
            m.collect({})
        with self.assertRaises(ValueError):
            m.collect(FIXTURE + FIXTURE)

    def test_protected_output(self):
        with self.assertRaises(ValueError):
            m.check_output(m.ROOT / 'src/data/episodes.json')
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / 'alias'
            alias.symlink_to(m.ROOT / 'src/data', target_is_directory=True)
            with self.assertRaises(ValueError):
                m.check_output(alias / 'episodes.json')

    def test_failures_preserve_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input.json', Path(directory) / 'output.json'
            output.write_text('preserved')
            for content in ('invalid json', '[]', '{}'):
                source.write_text(content)
                run = subprocess.run([sys.executable, str(SCRIPT), '--input', str(source), '--output', str(output)], capture_output=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(output.read_text(), 'preserved')
            with patch.object(sys, 'argv', [str(SCRIPT), '--output', str(output)]), patch.object(m.urllib.request, 'urlopen', side_effect=OSError('offline')):
                self.assertEqual(m.main(), 1)
            self.assertEqual(output.read_text(), 'preserved')
            m.write_output(output, 'new content')
            self.assertEqual(output.read_text(), 'new content')


if __name__ == '__main__':
    unittest.main()
