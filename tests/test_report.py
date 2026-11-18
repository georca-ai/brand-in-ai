"""Behavior tests for Unicode, metric denominators, rankings, and citations."""
import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'skills/brand-in-ai/scripts/report.py'
spec = importlib.util.spec_from_file_location('brand_report', PATH)
report = importlib.util.module_from_spec(spec) if PATH.exists() else None
if report:
    spec.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(report, 'report implementation must exist')
        self.config = {'brand': 'Acme', 'aliases': [], 'language_aliases': {'ja': ['アクメ']},
                       'questions': [{'id': 'q1', 'language': 'en', 'text': 'Recommend tools'},
                                     {'id': 'q2', 'language': 'ja', 'text': 'アクメはどうですか'}],
                       'models': [{'provider': 'p', 'model': 'm', 'mode': 'offline'}],
                       'samples': 3, 'report_language': 'en'}

    def row(self, sample=1, **changes):
        row = {'provider': 'p', 'model': 'm', 'mode': 'offline', 'question_id': 'q1',
               'language': 'en', 'sample': sample, 'status': 'ok', 'text': 'Acme',
               'timestamp': '2026-11-18T00:00:00Z', 'returned_model': 'm-v1',
               'citations': [], 'search_observed': None, 'usage': {}}
        row.update(changes)
        return row

    def test_unicode_matching_avoids_latin_substrings(self):
        for text, aliases, expected in [
            ('ＡＣＭＥ works', ['acme'], True), ('STRASSE', ['Straße'], True),
            ('cafe\u0301', ['café'], True), ('acmeish and preacme', ['acme'], False),
            ('我推荐Acme产品', ['Acme'], True), ('推荐小米手机', ['小米'], True),
            ('アクメがおすすめ', ['アクメ'], True), ('anything', [''], False),
            ('продукт', ['оду'], False), ('Acme_2', ['Acme'], False)]:
            with self.subTest(text=text):
                self.assertEqual(report.mentions(text, aliases), expected)

    def test_denominators_prompted_split_and_missing(self):
        rows = [self.row(), self.row(2, status='failed', text='Acme'),
                self.row(1, question_id='q2', language='ja', text='アクメです'),
                self.row(2, question_id='q2', language='ja', status='skipped')]
        result = report.summarize(self.config, rows)
        self.assertEqual([result[k] for k in ['expected_samples', 'valid_samples', 'failed_samples',
                                             'skipped_samples', 'missing_samples']], [6, 2, 1, 1, 2])
        self.assertEqual(len(result['groups']), 2)
        self.assertEqual([(g['prompted'], g['mentions'], g['valid_samples'], g['missing_samples'])
                          for g in result['groups']], [(False, 1, 1, 1), (True, 1, 1, 1)])
        self.assertEqual(len(result['summaries']), 2)
        self.assertEqual(report.summarize(self.config, [])['groups'][0]['mention_rate'], None)

    def test_explicit_rankings_first_list_and_absent_target_denominator(self):
        rows = [self.row(text='Recommended tools:\n1. Other\n2. Acme\n\nTop alternatives:\n1. Acme\n2. Third'),
                self.row(2, text='Best tools:\n1. Other\n2. Third'),
                self.row(3, text='Acme is useful.\nSteps:\n1. Install Acme\n2. Start it')]
        result = report.summarize(self.config, rows)
        group = result['groups'][0]
        self.assertEqual(group['ranked_samples'], 2)
        self.assertEqual(group['first_place_count'], 0)
        self.assertEqual(group['first_place_rate'], 0)
        self.assertEqual(group['rank_distribution'], {'2': 1})
        self.assertEqual(group['target_ranked_samples'], 1)
        self.assertEqual([x['target_rank'] for x in result['samples'][0]['rankings']], [2, 1])
        self.assertEqual(result['samples'][2]['rankings'], [])

    def test_citations_deduplicate_separate_channels_and_require_association(self):
        rows = [self.row(text='[Acme docs](https://example.com/acme) and https://example.com/acme. '
                             'Other source: https://other.test.',
                         citations=[{'url': 'https://example.com/acme', 'title': 'Acme docs'},
                                    {'url': 'https://example.com/acme'}, {'url': 'https://other.test'}]),
                self.row(2, text='https://other.test', citations=[{'url': 'https://other.test'}])]
        result = report.summarize(self.config, rows)
        for channel in ('api', 'body'):
            sources = {x['url']: x for x in result['citations'][channel]}
            self.assertEqual(sources['https://example.com/acme']['sample_count'], 1)
            self.assertEqual(sources['https://example.com/acme']['product_sample_count'], 1)
            self.assertEqual(sources['https://other.test']['sample_count'], 2)
            self.assertEqual(sources['https://other.test']['product_sample_count'], 0)

    def test_render_bilingual_preserves_raw_unicode_status_and_no_data(self):
        result = report.summarize(self.config, [self.row(status='failed', reason='timeout', text='错误')])
        for language, labels in [('en', ['No data', 'timeout', '错误', 'API', 'Missing']),
                                 ('zh', ['无数据', 'timeout', '错误', 'API', '缺失'])]:
            rendered = report.render(result, language)
            for label in labels:
                self.assertIn(label, rendered)
            self.assertIn('q1', rendered)
            self.assertIn('m-v1', rendered)
        with self.assertRaises(ValueError):
            report.render(result, 'fr')

    def test_rankings_reject_zero_repeated_and_nonconsecutive_markers(self):
        for text in ['Recommended tools:\n1. Other\n1. Acme',
                     'Recommended tools:\n0. Acme\n1. Other',
                     'Recommended tools:\n1. Other\n3. Acme']:
            with self.subTest(text=text):
                self.assertEqual(report.summarize(self.config, [self.row(text=text)])['samples'][0]['rankings'], [])

    def test_multilingual_and_question_context_rankings(self):
        for heading in ['', 'Produits recommandés:', 'Empfohlene Produkte:',
                        'Productos recomendados:', '추천 제품:']:
            with self.subTest(heading=heading):
                self.config['questions'][0]['text'] = 'Describe tools' if heading else 'Recommend tools'
                result = report.summarize(self.config, [self.row(text=heading + '\n1. Acme\n2. Other')])
                self.assertEqual(result['groups'][0]['first_place_rate'], 1.0)
        self.config['questions'][0]['text'] = 'Describe tools'
        result = report.summarize(self.config, [self.row(text='1. Acme\n2. Other')])
        self.assertEqual(result['groups'][0]['ranked_samples'], 0)

    def test_no_mutation_and_json_serializable(self):
        import json
        rows = [self.row()]
        original = copy.deepcopy(rows)
        json.dumps(report.summarize(self.config, rows), ensure_ascii=False)
        self.assertEqual(rows, original)


if __name__ == '__main__':
    unittest.main()
