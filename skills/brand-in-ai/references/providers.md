# Provider adapters

All requests go directly to the listed first-party HTTPS endpoint, using a single user question and no conversation history. Credentials come from environment variables; they are sent in headers, never query strings. Python's standard library is sufficient. Model IDs are configurable. Defaults below are starting points; model aliases, account access and regional availability may change.

| ID | Credential environment variable | Default model | Supported modes (default first) | Official API documentation |
| --- | --- | --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1-mini` | plain, search | [Responses](https://platform.openai.com/docs/api-reference/responses), [web search](https://platform.openai.com/docs/guides/tools-web-search) |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5` | plain, search | [Messages](https://docs.anthropic.com/en/api/messages), [web search](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool) |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` | plain, search | [generateContent](https://ai.google.dev/api/generate-content), [Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search) |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` | plain | [Chat completions](https://api-docs.deepseek.com/api/create-chat-completion) |
| `kimi` | `MOONSHOT_API_KEY` | `moonshot-v1-8k` | plain | [Moonshot platform](https://platform.moonshot.cn/docs/api/chat) |
| `grok` | `XAI_API_KEY` | `grok-3` | plain | [xAI API](https://docs.x.ai/docs/api-reference) |
| `sonar` | `PERPLEXITY_API_KEY` | `sonar` | search | [Chat completions](https://docs.perplexity.ai/api-reference/chat-completions-post) |
| `qwen` | `DASHSCOPE_API_KEY` | `qwen-plus` | plain | [Bailian OpenAI compatibility](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) |
| `glm` | `ZHIPU_API_KEY` | `glm-4-plus` | plain | [BigModel API](https://docs.bigmodel.cn/api-reference/模型-api/对话补全) |
| `mistral` | `MISTRAL_API_KEY` | `mistral-small-latest` | plain | [Mistral API](https://docs.mistral.ai/api/) |
| `minimax` | `MINIMAX_API_KEY` | `MiniMax-M2` | plain | [MiniMax OpenAI compatibility](https://platform.minimax.io/docs/api-reference/text-openai-api) |
| `doubao` | `ARK_API_KEY` | **Required explicit model or endpoint ID** | plain | [Volcengine Ark](https://www.volcengine.com/docs/82379/1494384) |

The Chinese mainland endpoints are used for Moonshot, Bailian, BigModel and Ark. Their keys must match that region. MiniMax uses the international endpoint. Switching a model name alone does not change region. Ark uses account-specific inference endpoint IDs, so there is no default.

## Request and response contracts

- OpenAI: `https://api.openai.com/v1/responses`, Bearer authentication, `input` question; search adds `tools: [{"type": "web_search_preview"}]`. Parses completed Responses output text, URL annotations, usage and actual model. A completed `web_search_call` is observable search; absence of one is false.
- Anthropic: `https://api.anthropic.com/v1/messages`, `x-api-key`, version header `2023-06-01`, `max_tokens: 4096`. Parses text content blocks and excludes thinking. Only `end_turn`/`stop_sequence` are complete. Truncation is an error, not an answer. Search adds `tools: [{"type": "web_search_20250305", "name": "web_search"}]`; text-block `web_search_result_location` citations preserve URL, title and cited text. A `server_tool_use` block named `web_search` or positive `usage.server_tool_use.web_search_requests` marks observed search. Explicit zero usage marks false when no search block exists; otherwise observation is unknown. A tool call indicates an attempted search, not necessarily a successful retrieval.
- Gemini: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, `x-goog-api-key`; search adds `tools: [{"google_search": {}}]`. Parses non-thought text, `modelVersion`, `usageMetadata`, and web grounding chunks. Search queries or web grounding chunks provide observable search evidence; otherwise observation is unknown.
- Other providers: Bearer-authenticated, non-streaming Chat Completions with one user message. Endpoints are recorded in `scripts/providers.py`. A `stop` finish reason and nonempty string content are required. Sonar additionally parses its top-level `citations` URL list; citations are treated as observable retrieval evidence. Their absence leaves search observation unknown.

All parsers reject empty answers, error envelopes, truncated output and malformed required fields with `ValueError`. Citation records contain `url` and optional `title`; body links are handled by the reporting layer. `search_observed: null` means the response does not show whether search ran, which is different from false. Requesting search mode alone never sets it to true. Search annotations and grounding are as reported by the provider.

Plain mode means no search tool is requested; the provider may still retrieve internally. Other search products are not supported yet. An unsupported mode is reported as skipped, not downgraded.

## Validation status — 2026-11-18

Live API verification is pending for all twelve integrations. Before a production run, confirm the endpoint, authentication, model, region, and search fields in the provider documentation, then send one test request with the configured credential.

Offline fixtures cover all twelve provider IDs, request isolation, credential headers, Unicode questions, search toggles, response parsing, citations, thinking exclusion, usage, and rejection of empty/error/incomplete responses. The fixtures are hand-written, not recorded from production. Run:

```sh
python3 -m unittest discover -s tests -p test_providers.py -v
```

Report live coverage separately from offline fixture coverage.
