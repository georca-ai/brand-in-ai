"""Deterministic, standard-library visibility metrics and bilingual reports."""
import copy
import html
import json
import re
import unicodedata
from collections import Counter


def _normal(text):
    return unicodedata.normalize('NFKC', text).casefold()


def _unspaced(char):
    code = ord(char)
    return (0x3400 <= code <= 0x9fff or 0x20000 <= code <= 0x323af
            or 0x3040 <= code <= 0x30ff or 0xac00 <= code <= 0xd7af
            or 0x0e00 <= code <= 0x0eff)


def _word(char):
    return char == '_' or unicodedata.category(char)[0] in 'LNM'


def mentions(text, aliases):
    """Match normalized aliases, respecting word boundaries in spaced scripts."""
    text = _normal(text)
    for alias in aliases:
        alias = _normal(alias).strip()
        if not alias:
            continue
        offset = 0
        while True:
            start = text.find(alias, offset)
            if start < 0:
                break
            end = start + len(alias)
            left = (start == 0 or not _word(alias[0]) or _unspaced(alias[0])
                    or not _word(text[start - 1]) or _unspaced(text[start - 1]))
            right = (end == len(text) or not _word(alias[-1]) or _unspaced(alias[-1])
                     or not _word(text[end]) or _unspaced(text[end]))
            if left and right:
                return True
            offset = start + 1
    return False


def _aliases(config, language):
    return [config['brand'], *config.get('aliases', []),
            *config.get('language_aliases', {}).get(language, [])]


_ORDERED = re.compile(r'^\s*(?:#{1,6}\s+)?(?:\*\*)?(\d{1,3})[.)、．]\s*(.+)$')
_RECOMMEND = re.compile(r'recommend|\btop\b|\bbest\b|\brank(?:ing|ed|ings)?\b|推荐|排名|排行|おすすめ|推奨|ランキング|recommand|classement|empfehl|empfohl|rangliste|besten|recomend|mejores|clasificación|추천|순위', re.I)
_URL = re.compile(r'https?://[^\s<>\[\]"\x60]+')
_LINK = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)(?:\s+"[^"]*")?\)')


def _rankings(text, aliases, question=''):
    """Only explicit numbered recommendations; do not infer prose order."""
    lists = []
    items = []
    context = []
    heading = ''

    def flush():
        if items and (_RECOMMEND.search(heading) or (not heading.strip() and len(items) >= 2 and _RECOMMEND.search(question))):
            ranks = [item['rank'] for item in items]
            # Repeated Markdown "1." markers or nonascending numbers are ambiguous.
            if ranks[0] >= 1 and all(b == a + 1 for a, b in zip(ranks, ranks[1:])):
                target = next((i['rank'] for i in items if mentions(i['text'], aliases)), None)
                lists.append({'heading': heading, 'items': copy.deepcopy(items), 'target_rank': target})
        items.clear()

    for line in text.splitlines():
        match = _ORDERED.match(unicodedata.normalize('NFKC', line))
        if match:
            number = int(match[1])
            if not items:
                heading = '\n'.join(context[-3:])
            items.append({'rank': number, 'text': match[2], 'evidence': line})
        elif line.strip():
            if items:
                flush()
                context = []
            context.append(line)
    flush()
    return lists


def _body_citations(text, aliases):
    associated = {}
    for match in _LINK.finditer(text):
        url = match[2]
        associated[url] = associated.get(url, False) or mentions(match[1], aliases)
    for match in _URL.finditer(text):
        url = match[0].rstrip('.,;:!?。，；：！？')
        while url.endswith(')') and url.count(')') > url.count('('):
            url = url[:-1]
        associated.setdefault(url, False)
    return [{'url': url, 'product_associated': value} for url, value in associated.items()]


def _stats(rows, expected):
    valid = [row for row in rows if row['status'] == 'ok']
    mentioned = sum(row['mentioned'] for row in valid)
    ranked = [row for row in valid if row['rankings']]
    ranks = [row['rankings'][0]['target_rank'] for row in ranked]
    first = ranks.count(1)
    return {'expected_samples': expected, 'valid_samples': len(valid),
            'failed_samples': sum(r['status'] == 'failed' for r in rows),
            'skipped_samples': sum(r['status'] == 'skipped' for r in rows),
            'missing_samples': expected - len(rows), 'mentions': mentioned,
            'mention_rate': mentioned / len(valid) if valid else None,
            'ranked_samples': len(ranked), 'target_ranked_samples': sum(r is not None for r in ranks),
            'first_place_count': first, 'first_place_rate': first / len(ranked) if ranked else None,
            'rank_distribution': dict(sorted(Counter(str(r) for r in ranks if r is not None).items()))}


def summarize(config, rows):
    """Summarize expected slots, using the latest success (or latest failure)."""
    by_slot = {}
    for row in rows:
        key = (row['provider'], row['model'], row['mode'], row['question_id'], row['sample'])
        if key not in by_slot or row['status'] == 'ok' or by_slot[key]['status'] != 'ok':
            by_slot[key] = row
    samples, groups = [], []
    for model in config['models']:
        for question in config['questions']:
            aliases = _aliases(config, question['language'])
            prompted = mentions(question['text'], aliases)
            selected = []
            for index in range(1, config['samples'] + 1):
                key = (model['provider'], model['model'], model['mode'], question['id'], index)
                if key not in by_slot:
                    continue
                row = copy.deepcopy(by_slot[key])
                row['prompted'] = prompted
                row['mentioned'] = row['status'] == 'ok' and mentions(row.get('text', ''), aliases)
                row['rankings'] = _rankings(row.get('text', ''), aliases, question['text']) if row['status'] == 'ok' else []
                row['body_citations'] = _body_citations(row.get('text', ''), aliases) if row['status'] == 'ok' else []
                row['api_citations'] = []
                if row['status'] == 'ok':
                    for citation in row.get('citations', []):
                        row['api_citations'].append({**citation, 'product_associated': mentions(
                            citation.get('title', '') + '\n' + citation.get('quote', ''), aliases)})
                selected.append(row)
                samples.append(row)
            groups.append({**model, 'language': question['language'], 'question_id': question['id'],
                           'question': question['text'], 'prompted': prompted,
                           **_stats(selected, config['samples'])})
    summaries = []
    seen = set()
    for group in groups:
        fields = ('provider', 'model', 'mode', 'language', 'prompted')
        key = tuple(group[f] for f in fields)
        if key in seen:
            continue
        seen.add(key)
        matching = [g for g in groups if tuple(g[f] for f in fields) == key]
        selected = [r for r in samples if tuple(r[f] for f in fields) == key]
        summaries.append({**dict(zip(fields, key)),
                          **_stats(selected, sum(g['expected_samples'] for g in matching))})
    citations = {}
    for channel in ('api', 'body'):
        counts, product_counts = Counter(), Counter()
        for row in samples:
            sources = row[channel + '_citations']
            counts.update({c['url'] for c in sources})
            product_counts.update({c['url'] for c in sources if c['product_associated']})
        citations[channel] = [{'url': url, 'sample_count': count,
                               'product_sample_count': product_counts[url]}
                              for url, count in sorted(counts.items())]
    expected = len(config['models']) * len(config['questions']) * config['samples']
    return {'brand': config['brand'], 'config': copy.deepcopy(config), **_stats(samples, expected),
            'groups': groups, 'summaries': summaries, 'samples': samples, 'citations': citations}


def _cell(value):
    return html.escape(str(value)).replace('|', '&#124;').replace('\n', '<br>')


def render(report, language):
    """Render metrics and complete raw evidence; no valid samples is not zero %."""
    if language not in ('zh', 'en'):
        raise ValueError('report language must be zh or en')
    zh = language == 'zh'
    def label(en, cn):
        return cn if zh else en
    def ratio(count, total):
        return f'{count}/{total} ({count / total:.1%})' if total else label('No data (0/0)', '无数据 (0/0)')
    lines = [f"# {label('Brand visibility', '品牌可见度')}: {_cell(report['brand'])}", '',
             label('These samples describe the specified API models, questions, times, and requested modes; they do not measure consumer chat applications.',
                   '本报告仅反映指定 API 模型、题库、时间和请求模式下的采样结果，不代表消费端聊天产品。'), '',
             f"{label('Expected / Valid / Failed / Skipped / Missing', '预期 / 有效 / 失败 / 跳过 / 缺失')}: "
             + ' / '.join(str(report[k]) for k in ('expected_samples', 'valid_samples', 'failed_samples', 'skipped_samples', 'missing_samples')), '',
             label('Mention rate uses valid answers only. First-place rate uses answers with a parseable recommendation list, including lists without the brand. Rank distribution uses answers with a determinable target rank. Only the first parseable list is used. Numbered lists require a recommendation/ranking cue in the heading, or a heading-free list of at least two items when the question requests recommendations. Positive consecutive numbers are required; repeated markers and unrecognized formats remain unranked. Heading cues support English, Chinese, Japanese, French, German, Spanish, and Korean.',
                   '提及率以有效回答为分母；首位率以含可解析推荐榜单的回答为分母（包括未出现目标产品的榜单）；排名分布仅含目标名次可判定的回答。主指标仅使用首个可解析榜单。编号列表须有推荐或排名标题；问题请求推荐时，无标题列表须至少两项。编号须为连续正整数，重复编号与无法识别的格式不推断名次。标题提示词支持英、中、日、法、德、西、韩文。'), '']
    for title, groups in [(label('Summary', '汇总'), report['summaries']),
                          (label('By question', '按问题展开'), report['groups'])]:
        lines += [f'## {title}', '',
                  '| ' + ' | '.join([label('Provider / model / mode', '提供方 / 模型 / 模式'),
                                      label('Language / question', '语言 / 问题'), label('Prompt type', '问题类型'),
                                      label('Mentions', '提及'), label('First place', '首位'),
                                      label('Rank distribution (denominator)', '排名分布（分母）'),
                                      label('Failed / skipped / missing', '失败 / 跳过 / 缺失')]) + ' |',
                  '|---|---|---|---|---|---|---|']
        for g in groups:
            lines.append('| ' + ' | '.join(map(_cell, [
                f"{g['provider']} / {g['model']} / {g['mode']}",
                f"{g['language']} / {g.get('question_id', '*')}",
                label('Prompted', '提示提及') if g['prompted'] else label('Natural', '自然提及'),
                ratio(g['mentions'], g['valid_samples']), ratio(g['first_place_count'], g['ranked_samples']),
                f"{json.dumps(g['rank_distribution'], ensure_ascii=False)} (n={g['target_ranked_samples']})",
                f"{g['failed_samples']} / {g['skipped_samples']} / {g['missing_samples']}"
            ])) + ' |')
        lines.append('')
    lines += [f"## {label('Citation URLs', '引用 URL')}", '',
              label('API and body URLs are counted separately, once per sample. Product association requires a matching citation title/quote or Markdown link label; other URLs remain answer-level sources.',
                    'API 与正文 URL 分别按样本去重计数。仅当引用标题、引文或 Markdown 链接标签命中产品时标记关联，其余为回答级出处。'), '',
              '| ' + ' | '.join([label('Channel', '渠道'), 'URL', label('Samples', '样本数'), label('Product-associated samples', '产品关联样本数')]) + ' |',
              '|---|---|---|---|']
    for channel, sources in report['citations'].items():
        for source in sources:
            lines.append(f"| {channel.upper()} | {_cell(source['url'])} | {source['sample_count']} | {source['product_sample_count']} |")
    lines += ['', f"## {label('Raw answers and evidence', '原始回答与证据')}", '']
    for row in report['samples']:
        lines += [f"### {_cell(row['provider'])} / {_cell(row['model'])} / {_cell(row['question_id'])} / {row['sample']}", '',
                  f"{label('Status', '状态')}: {_cell(row['status'])}; {label('Time', '时间')}: {_cell(row.get('timestamp', ''))}; "
                  f"{label('Returned model', '返回模型')}: {_cell(row.get('returned_model', ''))}; "
                  f"{label('Requested mode', '请求模式')}: {_cell(row['mode'])}; "
                  f"{label('Observed search', '可观察搜索状态')}: {_cell(row.get('search_observed'))}", '']
        if row.get('reason'):
            lines += [_cell(row['reason']), '']
        # Dynamic fences preserve arbitrary model text without breaking Markdown.
        raw = row.get('text', '')
        fence = '`' * max(3, 1 + max((len(m[0]) for m in re.finditer(r'`+', raw)), default=0))
        lines += [fence + 'text', raw, fence, '', '```json',
                  json.dumps({key: row.get(key) for key in ('citations', 'body_citations', 'rankings', 'usage')}, ensure_ascii=False, indent=2).replace('`', '\\u0060'),
                  '```', '']
    return '\n'.join(lines)
