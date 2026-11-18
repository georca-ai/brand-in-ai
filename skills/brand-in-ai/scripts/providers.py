"""Standard-library request builders and response parsers for first-party APIs.

No credentials, network calls, or target brand information are stored here.
See references/providers.md for coverage and validation limitations.
"""
from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class Provider:
    key_env: str
    default_model: str | None
    endpoint: str
    modes: tuple[str, ...] = ('plain',)


PROVIDERS = {
    'openai': Provider('OPENAI_API_KEY', 'gpt-4.1-mini', 'https://api.openai.com/v1/responses', ('plain', 'search')),
    'anthropic': Provider('ANTHROPIC_API_KEY', 'claude-sonnet-4-5', 'https://api.anthropic.com/v1/messages', ('plain', 'search')),
    'gemini': Provider('GEMINI_API_KEY', 'gemini-2.5-flash', 'https://generativelanguage.googleapis.com/v1beta/models/', ('plain', 'search')),
    'deepseek': Provider('DEEPSEEK_API_KEY', 'deepseek-chat', 'https://api.deepseek.com/chat/completions'),
    'kimi': Provider('MOONSHOT_API_KEY', 'moonshot-v1-8k', 'https://api.moonshot.cn/v1/chat/completions'),
    'grok': Provider('XAI_API_KEY', 'grok-3', 'https://api.x.ai/v1/chat/completions'),
    'sonar': Provider('PERPLEXITY_API_KEY', 'sonar', 'https://api.perplexity.ai/chat/completions', ('search',)),
    'qwen': Provider('DASHSCOPE_API_KEY', 'qwen-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'),
    'glm': Provider('ZHIPU_API_KEY', 'glm-4-plus', 'https://open.bigmodel.cn/api/paas/v4/chat/completions'),
    'mistral': Provider('MISTRAL_API_KEY', 'mistral-small-latest', 'https://api.mistral.ai/v1/chat/completions'),
    'minimax': Provider('MINIMAX_API_KEY', 'MiniMax-M2', 'https://api.minimax.io/v1/chat/completions'),
    'doubao': Provider('ARK_API_KEY', None, 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'),
}


def _provider(name, mode):
    if name not in PROVIDERS:
        raise ValueError(f'Unknown provider: {name}')
    spec = PROVIDERS[name]
    if mode not in spec.modes:
        raise ValueError(f'{name} does not support mode {mode}')
    return spec


def request_spec(provider: str, model: str, mode: str, question: str, key: str) -> tuple:
    spec = _provider(provider, mode)
    if not all(isinstance(value, str) and value.strip() for value in (model, question, key)):
        raise ValueError('Model, question and API key must be nonempty strings')
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    url = spec.endpoint
    body = {'model': model, 'messages': [{'role': 'user', 'content': question}], 'stream': False}
    if provider == 'openai':
        body = {'model': model, 'input': question}
        if mode == 'search':
            body['tools'] = [{'type': 'web_search_preview'}]
    elif provider == 'anthropic':
        headers = {'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01'}
        body['max_tokens'] = 4096
        if mode == 'search':
            body['tools'] = [{'type': 'web_search_20250305', 'name': 'web_search'}]
    elif provider == 'gemini':
        headers = {'Content-Type': 'application/json', 'x-goog-api-key': key}
        url += quote(model, safe='') + ':generateContent'
        body = {'contents': [{'role': 'user', 'parts': [{'text': question}]}]}
        if mode == 'search':
            body['tools'] = [{'google_search': {}}]
    return url, headers, body


def parse_response(provider: str, mode: str, payload: dict) -> dict:
    """Reject partial/empty/error responses; None means search was unobservable."""
    _provider(provider, mode)
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('Invalid or error API response')
    citations = []

    def cite(url, title=None, quote_text=None):
        if isinstance(url, str) and url.startswith(('https://', 'http://')):
            item = {'url': url}
            if isinstance(title, str) and title:
                item['title'] = title
            if isinstance(quote_text, str) and quote_text:
                item['quote'] = quote_text
            if item not in citations:
                citations.append(item)

    observed = None
    returned_model = payload.get('model')
    usage = payload.get('usage')
    try:
        if provider == 'openai':
            if payload.get('status') != 'completed':
                raise ValueError('OpenAI response is not completed')
            chunks = []
            observed = False
            for item in payload['output']:
                if item.get('type') == 'web_search_call' and item.get('status') == 'completed':
                    observed = True
                if item.get('type') == 'message':
                    for block in item.get('content', []):
                        if block.get('type') == 'output_text':
                            chunks.append(block['text'])
                            for annotation in block.get('annotations', []):
                                if annotation.get('type') == 'url_citation':
                                    cite(annotation.get('url'), annotation.get('title'))
            text = '\n'.join(chunks)
        elif provider == 'anthropic':
            if payload.get('stop_reason') not in ('end_turn', 'stop_sequence'):
                raise ValueError('Anthropic response is not completed')
            chunks = []
            for block in payload['content']:
                if block.get('type') == 'server_tool_use' and block.get('name') == 'web_search':
                    observed = True
                if block.get('type') == 'text':
                    chunks.append(block['text'])
                    for citation in block.get('citations', []):
                        if citation.get('type') == 'web_search_result_location':
                            cite(citation.get('url'), citation.get('title'), citation.get('cited_text'))
            text = '\n'.join(chunks)
            searches = (usage or {}).get('server_tool_use', {}).get('web_search_requests')
            if observed is not True and isinstance(searches, int) and searches >= 0:
                observed = searches > 0
        elif provider == 'gemini':
            candidate = payload['candidates'][0]
            if candidate.get('finishReason') != 'STOP':
                raise ValueError('Gemini response is not completed')
            text = '\n'.join(block['text'] for block in candidate['content']['parts'] if 'text' in block and not block.get('thought'))
            returned_model = payload.get('modelVersion')
            usage = payload.get('usageMetadata')
            grounding = candidate.get('groundingMetadata', {})
            for chunk in grounding.get('groundingChunks', []):
                web = chunk.get('web', {})
                cite(web.get('uri'), web.get('title'))
            if grounding.get('webSearchQueries') or citations:
                observed = True
        else:
            choice = payload['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('Chat response is not completed')
            text = choice['message']['content']
            if provider == 'sonar':
                for url in payload.get('citations', []):
                    cite(url)
                if citations:
                    observed = True
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed API response') from exc
    if not isinstance(text, str) or not text.strip():
        raise ValueError('API response has no answer text')
    if returned_model is not None and not isinstance(returned_model, str):
        raise ValueError('Invalid returned model identifier')
    result = {'text': text, 'returned_model': returned_model, 'citations': citations, 'search_observed': observed}
    if isinstance(usage, dict):
        result['usage'] = usage
    return result
