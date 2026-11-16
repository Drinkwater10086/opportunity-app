"""Bounded public API adapters. No arbitrary URLs or private profile harvesting."""
from datetime import datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
import re
import threading
import time
import hashlib
import requests
import source_policy

NAMES = {'github': 'GitHub', 'github_issues': 'GitHub', 'stackoverflow': 'Stack Overflow',
         'hackernews': 'Hacker News', 'superuser': 'Super User', 'workplace': 'The Workplace',
         'n8n': 'n8n Community', 'make': 'Make Community', 'nodered': 'Node-RED Forum', 'v2ex':'V2EX', 'arxiv':'arXiv',
         'ithome':'IT之家','kaggle':'Kaggle','producthunt':'Product Hunt','infoq':'InfoQ中国','qbitai':'量子位'}
STACK_SITES = {'stackoverflow', 'superuser', 'workplace'}
_guard = threading.Lock()
_cooldown = {}


def provider_for(source):
    source_policy.require_allowed([source])
    if source not in NAMES:
        raise ValueError('不支持的数据来源')
    return 'stackoverflow' if source in STACK_SITES else ('hackernews' if source == 'hackernews' else 'github')


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_html(value):
    parser = TextParser()
    parser.feed(value)
    return unescape(' '.join(parser.parts))


def redact(value):
    # Do not persist obvious contact details or API keys embedded in public text.
    value = re.sub(r'(?i)(\bBearer\s+)[A-Za-z0-9_./+=-]{8,}', r'\1[密钥已隐去]', value)
    value = re.sub(r'''(?i)((?:api[_-]?key|access[_-]?token|client[_-]?secret)["']?\s*[:=]\s*["']?)[A-Za-z0-9_./+=-]{8,}''',
                   r'\1[密钥已隐去]', value)
    value = re.sub(r'(?i)((?:\bphone|\btelephone|\btel|联系电话|电话号码|手机号)\s*[:：=]\s*)\+?\d[\d ()-]{5,}\d',
                   r'\1[电话已隐去]', value)
    value = re.sub(r'(?<![\w\d])\+(?:\d[ \t().-]*){7,14}\d(?!\d)', '[电话已隐去]', value)
    value = re.sub(r'(?<!\d)\d{3}[- .]\d{3}[- .]\d{4}(?!\d)', '[电话已隐去]', value)
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[邮箱已隐去]', value)
    value = re.sub(r'(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)', '[手机号已隐去]', value)
    return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,})\b', '[密钥已隐去]', value)


def iso(timestamp):
    if timestamp is None:
        return None
    try:
        if type(timestamp) not in (int, float):
            raise ValueError('invalid timestamp type')
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        raise ValueError('来源返回无效发布时间或更新时间') from None


def source_time(value):
    """Parse provider timestamps without guessing missing time zones."""
    try:
        if type(value) in (int, float):
            parsed = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('missing timezone')
        else:
            raise ValueError('missing timestamp')
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise ValueError('来源返回无效时间') from None


def queries(value):
    terms = list(dict.fromkeys(v.strip() for v in value.splitlines() if v.strip()))
    if not 1 <= len(terms) <= 8 or any(not 2 <= len(v) <= 160 for v in terms):
        raise ValueError('检索词每行一组，共1–8组，每组2–160字符')
    return terms


LOCAL_QUERY_MATCH_VERSION='ascii-word-boundary-and-tokens-v1'


def matches_local_query(text,query):
    """Feed-local AND tokens; API-specific search syntax is not interpreted."""
    content=text.casefold()
    words=query.casefold().split()
    if not words:return False
    for word in words:
        pattern=re.escape(word)
        if word.isascii():pattern=r'(?<![a-z0-9_])'+pattern+r'(?![a-z0-9_])'
        if not re.search(pattern,content):return False
    return True


def github_issue_search_scope(query):
    # Respect a real qualifier, not the literal text "in:comments" in quotes.
    unquoted=re.sub(r'"(?:\\.|[^"\\])*"',' ',query)
    qualified=bool(re.search(r'(?<!\S)in:',unquoted,re.I))
    return (query if qualified else query+' in:title,body'), {
        'mode':'user_qualified' if qualified else 'title_body_default',
        'retained_fields':['title','body'],'comments_collected':False,
        'note':'按用户in:限定搜索；仅保留主帖，评论命中可能未保留' if qualified else '默认仅搜索标题和主帖正文，不将未采集评论作为命中范围'}


def fetch(source, query, limit, days, window_end=None):
    """Bounded pagination per query, preserving page provenance and partial data."""
    source_policy.require_allowed([source])
    window_end = window_end or datetime.now(timezone.utc)
    if window_end.tzinfo is None:
        raise ValueError('采集窗口必须包含时区')
    window_end = window_end.astimezone(timezone.utc).replace(microsecond=0)
    if source in ('v2ex', 'arxiv', 'ithome', 'kaggle', 'producthunt', 'infoq', 'qbitai'):
        from extended_sources import fetch as fetch_extended
        return fetch_extended(source, query, limit, days, window_end)
    if source in ('n8n', 'make', 'nodered'):
        from forum_sources import fetch_forum
        return fetch_forum(source, query, limit, days, window_end=window_end)
    provider = provider_for(source)
    with _guard:
        remaining = _cooldown.get(provider, 0) - time.monotonic()
    if remaining > 30:
        raise ValueError(f'{NAMES[source]} 请求冷却中，请约 {int(remaining)+1} 秒后重试')
    records, pages, seen = [], [], set()
    terms = queries(query)
    for term_index, term in enumerate(terms):
        page_size = min(limit, 100)
        page_count = (limit+page_size-1)//page_size
        for page in range(1, page_count+1):
            try:
                items, meta = fetch_page(source, term, page_size, days, page, window_end=window_end)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                if not pages:
                    raise
                return records, {'pages': pages, 'complete': False, 'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                                 'window_start': (window_end-timedelta(days=days)).isoformat(), 'window_end': window_end.isoformat(),
                                 'returned_count': len(records), 'scope': '采集中断，保留已成功页面'}
            pages.append(meta)
            for item in items[:max(0, limit-(page-1)*page_size)]:
                if item['url'] not in seen:
                    seen.add(item['url']); records.append(item)
            if meta.get('invalid_date_count', 0) or meta.get('outside_window_count', 0):
                return records, {'pages': pages, 'complete': False,
                                 'error': '来源返回缺失、无效或超出窗口的时间，已保留通过校验的记录',
                                 'returned_count': len(records), 'scope': '存在时间异常，不能作为完整采集',
                                 'window_start': (window_end-timedelta(days=days)).isoformat(),
                                 'window_end': window_end.isoformat()}
            if meta.get('incomplete_results') is True:
                return records, {'pages': pages, 'complete': False,
                                 'error': '搜索接口返回不完整结果，已保留已返回记录；请缩小查询范围',
                                 'returned_count': len(records), 'scope': '搜索结果不完整，不能作为完整采集',
                                 'window_start': (window_end-timedelta(days=days)).isoformat(),
                                 'window_end': window_end.isoformat()}
            more = meta.get('has_more')
            exhausted = more is False or (more is None and page*page_size >= min(meta.get('total_count') or 0, 1000))
            needs_request = (not exhausted and page < page_count) or term_index < len(terms)-1
            if meta.get('quota_remaining') == 0 and needs_request:
                return records, {'pages': pages, 'complete': False, 'error': '采集接口配额耗尽', 'returned_count': len(records),
                                 'window_start': (window_end-timedelta(days=days)).isoformat(), 'window_end': window_end.isoformat()}
            if exhausted:
                break
    return records, {'pages': pages, 'complete': True, 'returned_count': len(records), 'backoff': pages[-1].get('backoff') if pages else None,
                     'window_start': (window_end-timedelta(days=days)).isoformat(), 'window_end': window_end.isoformat(),
                     'scope': f'每组检索词每来源最多{limit}条，跨检索词按URL去重；不代表全网'}


def fetch_page(source, query, limit, days, page=1, window_end=None):
    """One public search page, with shared provider pacing."""
    retrieved_at = datetime.now(timezone.utc)
    now = window_end or retrieved_at
    if now.tzinfo is None:
        raise ValueError('采集窗口必须包含时区')
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    since = now - timedelta(days=days)
    headers = {'User-Agent': 'AI-Opportunity-Research-Prototype', 'Accept': 'application/json'}
    # Reserve cooldown before requesting; never bypass provider backoff.
    provider = provider_for(source)
    while True:
        with _guard:
            remaining = _cooldown.get(provider, 0) - time.monotonic()
            if remaining > 30:
                raise ValueError(f'{NAMES[source]} 请求冷却中，请约 {int(remaining)+1} 秒后重试')
            if remaining <= 0:
                _cooldown[provider] = time.monotonic() + (7 if provider == 'github' else 1)
                break
        time.sleep(min(remaining, 30))
    if source == 'github':
        params = {'q': f'{query} pushed:{since.strftime("%Y-%m-%dT%H:%M:%SZ")}..{now.strftime("%Y-%m-%dT%H:%M:%SZ")} archived:false fork:false',
                  'sort': 'stars', 'order': 'desc', 'per_page': limit, 'page': page}
        headers['X-GitHub-Api-Version'] = '2022-11-28'
        endpoint = 'https://api.github.com/search/repositories'
    elif source == 'github_issues':
        effective,issue_scope=github_issue_search_scope(query)
        params = {'q': f'{effective} is:issue is:public created:{since.strftime("%Y-%m-%dT%H:%M:%SZ")}..{now.strftime("%Y-%m-%dT%H:%M:%SZ")}',
                  'sort': 'comments', 'order': 'desc', 'per_page': limit, 'page': page}
        headers['X-GitHub-Api-Version'] = '2022-11-28'
        endpoint = 'https://api.github.com/search/issues'
    elif source == 'hackernews':
        params = {'query': query, 'tags': '(story,comment)', 'hitsPerPage': limit, 'page': page-1,
                  'numericFilters': f'created_at_i>={int(since.timestamp())},created_at_i<={int(now.timestamp())}'}
        endpoint = 'https://hn.algolia.com/api/v1/search'
    else:
        params = {'site': source, 'q': query, 'pagesize': limit, 'page': page,
                  'fromdate': int(since.timestamp()), 'todate': int(now.timestamp()),
                  'sort': 'votes', 'order': 'desc', 'filter': 'withbody'}
        endpoint = 'https://api.stackexchange.com/2.3/search/advanced'
    response = requests.get(endpoint, params=params, headers=headers, timeout=30)
    retrieved_at = datetime.now(timezone.utc)
    if response.status_code in (403, 429):
        with _guard:
            retry = response.headers.get('Retry-After', '60')
            delay = int(retry) if retry.isdigit() else 60
            reset = response.headers.get('X-RateLimit-Reset', '')
            if reset.isdigit():
                delay = max(delay, int(reset)-time.time())
            _cooldown[provider] = time.monotonic() + max(60, delay)
        raise ValueError(f'{NAMES[source]} 拒绝访问或限流；请稍后重试')
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f'{NAMES[source]} 返回非对象格式，已停止采集')
    items = payload.get('hits' if source == 'hackernews' else 'items')
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError(f'{NAMES[source]} 返回无效记录列表，已停止采集')
    for key in (('nbPages', 'nbHits') if source == 'hackernews' else ('total_count', 'quota_remaining')):
        value = payload.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f'{NAMES[source]} 返回无效数量字段：{key}')
    if source == 'hackernews' and type(payload.get('nbPages')) is not int:
        raise ValueError(f'{NAMES[source]} 缺少有效分页数量')
    if source in ('github', 'github_issues') and type(payload.get('total_count')) is not int:
        raise ValueError(f'{NAMES[source]} 缺少分页所需的结果总数')
    if source in STACK_SITES and type(payload.get('has_more')) is not bool:
        raise ValueError(f'{NAMES[source]} 缺少有效分页状态')
    if payload.get('has_more') is not None and type(payload['has_more']) is not bool:
        raise ValueError(f'{NAMES[source]} 返回无效分页状态')
    if payload.get('incomplete_results') is not None and type(payload['incomplete_results']) is not bool:
        raise ValueError(f'{NAMES[source]} 返回无效完整性状态')
    if payload.get('backoff'):
        with _guard:
            _cooldown[provider] = max(_cooldown[provider], time.monotonic() + int(payload['backoff']))
    if payload.get('error_id'):
        raise ValueError(f'{NAMES[source]} 返回接口错误，请检查请求或稍后重试')
    records = []
    invalid_date_count = outside_window_count = 0
    for item in items:
        if source == 'github_issues' and 'pull_request' in item:
            continue
        try:
            published = source_time(item.get('creation_date') if source in STACK_SITES else item.get('created_at'))
            window_date = source_time(item.get('pushed_at')) if source == 'github' else published
        except ValueError:
            invalid_date_count += 1
            continue
        if not since <= window_date <= now:
            outside_window_count += 1
            continue
        if source == 'github':
            raw_text = redact(item.get('description') or '')
            records.append(dict(title=redact(item['name']), raw_text=raw_text,
                                url=item['html_url'], published_at=item.get('created_at'),
                                updated_at=item.get('pushed_at'), stars=item.get('stargazers_count'),
                                heat={'星标数': item.get('stargazers_count')},
                                license='项目简介；具体项目许可需在原链接核验',
                                provenance={'body_available': bool(raw_text.strip()),
                                            'body_method': '项目简介' if raw_text.strip() else '仅项目名称，接口未提供简介'}))
        elif source == 'github_issues':
            body=item.get('body')
            if body is not None and not isinstance(body,str):raise ValueError('GitHub Issue正文不是Markdown字符串，已停止该页采集')
            raw_text = redact(body or '')
            records.append(dict(title=redact(item['title']), raw_text=raw_text,
                                url=item['html_url'], published_at=item.get('created_at'),
                                updated_at=item.get('updated_at'), stars=None,
                                heat={'评论数': item.get('comments')},
                                license='公开问题正文；仅留存研究必要文本，许可须核对来源',
                                provenance={'body_available': bool(raw_text.strip()),
                                            'body_method': '公开Issue Markdown正文；未采集评论' if raw_text.strip() else '仅问题标题，接口未提供正文',
                                            'transport_format':'json','content_format':'markdown','search_scope':issue_scope},
                                reliability={'retained_body_sha256':hashlib.sha256(raw_text.encode('utf8')).hexdigest(),
                                             'note':'仅主帖留存正文，用户自述未经独立核实，评论未采集'}))
        elif source == 'hackernews':
            is_comment = 'comment' in item.get('_tags', [])
            title = item.get('story_title') if is_comment else item.get('title')
            text = item.get('comment_text') if is_comment else item.get('story_text')
            raw_text = redact(plain_html(text or ''))
            records.append(dict(title=redact(plain_html(title or 'Hacker News 讨论')),
                                raw_text=raw_text,
                                url=f"https://news.ycombinator.com/item?id={item['objectID']}",
                                published_at=item.get('created_at'), updated_at=None, stars=None,
                                heat={'得分': item.get('points'), '评论数': item.get('num_comments')},
                                license='Hacker News 公开讨论；许可须核对原帖，仅留存研究必要文本',
                                provenance={'item_type': 'comment' if is_comment else 'story',
                                            'parent_story_id': item.get('story_id'),
                                            'body_available': bool(raw_text.strip()),
                                            'body_method': ('Hacker News 站内评论正文' if is_comment else 'Hacker News 站内帖子正文') if raw_text.strip() else '仅标题，未采集外链文章正文',
                                            'search_service': 'Algolia HN Search'}))
        else:
            raw_text = redact(plain_html(item.get('body') or ''))
            records.append(dict(title=redact(unescape(item['title'])), raw_text=raw_text,
                                url=item['link'], published_at=iso(item.get('creation_date')),
                                updated_at=iso(item.get('last_activity_date')), stars=None,
                                heat={'浏览数': item.get('view_count'), '得分': item.get('score'),
                                      '回答数': item.get('answer_count')},
                                license=(item['content_license'].strip() if isinstance(item.get('content_license'), str)
                                         and item['content_license'].strip() else '接口未提供内容许可版本，请核对原帖'),
                                provenance={'body_available': bool(raw_text.strip()),
                                            'body_method': '公开问答正文' if raw_text.strip() else '仅问题标题，接口未提供正文'}))
    return records, {**({'search_scope':issue_scope} if source=='github_issues' else {}),
                     'endpoint': endpoint, 'params': params, 'retrieved_at': retrieved_at.isoformat(),
                     'incomplete_results': payload.get('incomplete_results'),
                     'invalid_date_count': invalid_date_count, 'outside_window_count': outside_window_count,
                     'returned_count': len(records),
                     'has_more': page < payload['nbPages'] if source == 'hackernews' else payload.get('has_more'),
                     'total_count': payload.get('nbHits') if source == 'hackernews' else payload.get('total_count'),
                     'quota_remaining': payload.get('quota_remaining'),
                     'backoff': payload.get('backoff'), 'scope': f'第{page}页，不代表全网或全部命中记录'}
