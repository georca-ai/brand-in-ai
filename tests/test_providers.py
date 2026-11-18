import importlib.util
import pathlib
import sys
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'skills/brand-in-ai/scripts/providers.py'
sys.path.insert(0, str(SCRIPT.parent))
try:
    import providers
except ImportError:
    providers = None


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(providers, 'provider adapters must exist')

    def test_registry_and_requests(self):
        expected = {'openai', 'anthropic', 'gemini', 'deepseek', 'kimi', 'grok',
                    'sonar', 'qwen', 'glm', 'mistral', 'minimax', 'doubao'}
        self.assertEqual(set(providers.PROVIDERS), expected)
        for name, spec in providers.PROVIDERS.items():
            self.assertTrue(spec.key_env)
            for mode in spec.modes:
                with self.subTest(provider=name, mode=mode):
                    url, headers, body = providers.request_spec(name, 'configured-model', mode, '推荐工具？', 'secret')
                    self.assertTrue(url.startswith('https://'))
                    self.assertNotIn('secret', url)
                    self.assertIn('secret', str(headers))
                    self.assertIn('推荐工具？', str(body))
                    self.assertNotIn('system', str(body))
                    self.assertIn('configured-model', url + str(body))
        self.assertEqual(providers.PROVIDERS['sonar'].modes, ('search',))
        self.assertIsNone(providers.PROVIDERS['doubao'].default_model)

    def test_search_requests_and_validation(self):
        for name in ('openai', 'gemini'):
            plain = providers.request_spec(name, 'model', 'plain', 'question', 'key')[2]
            search = providers.request_spec(name, 'model', 'search', 'question', 'key')[2]
            self.assertNotIn('tools', plain)
            self.assertIn('tools', search)
        for args in [('missing','m','plain','q','k'), ('deepseek','m','search','q','k'), ('doubao','','plain','q','k')]:
            with self.assertRaises(ValueError):
                providers.request_spec(*args)

    def test_chat_providers_and_sonar_citations(self):
        payload = {'model': 'actual', 'choices': [{'finish_reason':'stop','message': {'content': '工具推荐'}}], 'usage': {'total_tokens': 7}}
        for name in ('deepseek','kimi','grok','qwen','glm','mistral','minimax','doubao','sonar'):
            result = providers.parse_response(name, providers.PROVIDERS[name].modes[0], payload)
            self.assertEqual(result['text'], '工具推荐')
            self.assertEqual(result['returned_model'], 'actual')
            self.assertEqual(result['usage']['total_tokens'], 7)
            self.assertIsNone(result['search_observed'])
        payload['citations'] = ['https://example.org/a']
        result = providers.parse_response('sonar', 'search', payload)
        self.assertEqual(result['citations'], [{'url': 'https://example.org/a'}])
        self.assertIs(result['search_observed'], True)

    def test_openai_annotations_and_search_calls(self):
        payload = {'status':'completed','model':'actual','output':[
            {'type':'web_search_call','status':'completed'},
            {'type':'message','content':[{'type':'output_text','text':'answer','annotations':[
                {'type':'url_citation','url':'https://example.org','title':'Source'}]}]}]}
        result = providers.parse_response('openai','search',payload)
        self.assertEqual(result['text'], 'answer')
        self.assertEqual(result['citations'], [{'url':'https://example.org','title':'Source'}])
        self.assertIs(result['search_observed'], True)
        payload['output'].pop(0)
        payload['output'][0]['content'][0]['annotations'] = []
        self.assertIs(providers.parse_response('openai','search',payload)['search_observed'], False)

    def test_anthropic_and_gemini(self):
        claude = {'type':'message','stop_reason':'end_turn','model':'actual','content':[{'type':'thinking','thinking':'hidden'}, {'type':'text','text':'answer'}]}
        self.assertEqual(providers.parse_response('anthropic','plain',claude)['text'], 'answer')
        gemini = {'modelVersion':'actual','candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'hidden'},{'text':'answer'}]},'groundingMetadata':{'groundingChunks':[{'web':{'uri':'https://example.org','title':'Source'}}], 'webSearchQueries':['query']}}]}
        result = providers.parse_response('gemini','search',gemini)
        self.assertEqual(result['text'],'answer')
        self.assertEqual(result['returned_model'],'actual')
        self.assertEqual(result['citations'],[{'url':'https://example.org','title':'Source'}])
        self.assertIs(result['search_observed'],True)

    def test_anthropic_native_search(self):
        body = providers.request_spec('anthropic', 'model', 'search', 'question', 'key')[2]
        self.assertEqual(body['tools'], [{'type': 'web_search_20250305', 'name': 'web_search'}])
        payload = {'stop_reason': 'end_turn', 'content': [
            {'type': 'server_tool_use', 'name': 'web_search', 'id': 'tool1'},
            {'type': 'text', 'text': 'answer', 'citations': [
                {'type': 'web_search_result_location', 'url': 'https://example.org',
                 'title': 'Source', 'cited_text': 'quoted source'}]}]}
        result = providers.parse_response('anthropic', 'search', payload)
        self.assertIs(result['search_observed'], True)
        self.assertEqual(result['citations'], [{'url': 'https://example.org', 'title': 'Source', 'quote': 'quoted source'}])
        payload['content'] = [{'type': 'text', 'text': 'answer'}]
        payload['usage'] = {'server_tool_use': {'web_search_requests': 1}}
        self.assertIs(providers.parse_response('anthropic', 'search', payload)['search_observed'], True)
        payload['usage']['server_tool_use']['web_search_requests'] = 0
        self.assertIs(providers.parse_response('anthropic', 'search', payload)['search_observed'], False)

    def test_rejects_empty_error_and_incomplete(self):
        for name, spec in providers.PROVIDERS.items():
            for payload in ({}, {'error':{'message':'bad'}}, {'choices':[]}):
                with self.subTest(provider=name,payload=payload), self.assertRaises(ValueError):
                    providers.parse_response(name,spec.modes[0],payload)
        bad = [('openai',{'status':'incomplete','output':[]}),
               ('anthropic',{'stop_reason':'max_tokens','content':[{'type':'text','text':'partial'}]}),
               ('gemini',{'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}]}),
               ('deepseek',{'choices':[{'finish_reason':'length','message':{'content':'partial'}}]})]
        for name,payload in bad:
            with self.assertRaises(ValueError):
                providers.parse_response(name,'plain',payload)


if __name__ == '__main__':
    unittest.main()
