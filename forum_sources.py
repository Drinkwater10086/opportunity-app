"""Official community public posts, bounded recent scan; never crawl /search."""
from datetime import datetime, timezone, timedelta
import hashlib
import time
from urllib.robotparser import RobotFileParser
import requests
import sources
import source_policy

FORUMS = {'n8n': 'community.n8n.io', 'make': 'community.make.com',
          'nodered': 'discourse.nodered.org'}
USER_AGENT = 'AI-Opportunity-Research-Prototype'
MAX_PAGES = 10
MAX_DETAIL_REQUESTS = 30


def public_get(source, url, params=None):
    source_policy.require_allowed([source])
    with sources._guard:
        remaining = sources._cooldown.get(source, 0)-time.monotonic()
    if remaining > 30:
        raise ValueError('社区接口冷却中，请稍后重试')
    if remaining > 0:
        time.sleep(remaining)
    with sources._guard:
        sources._cooldown[source] = time.monotonic()+1
    r = requests.get(url, params=params, headers={'User-Agent': USER_AGENT},
                     timeout=30, allow_redirects=False)
    if r.status_code == 429:
        retry = r.headers.get('Retry-After', '60')
        with sources._guard:
            sources._cooldown[source] = time.monotonic()+max(60, int(retry) if retry.isdigit() else 60)
        raise ValueError('社区接口限流；已停止采集')
    if 300 <= r.status_code < 400:
        raise ValueError('社区接口发生重定向，需重新核验来源')
    r.raise_for_status()
    return r


def fetch_forum(source, query, limit, days, window_end=None):
    source_policy.require_allowed([source])
    host = FORUMS[source]
    base = 'https://'+host
    endpoint = base+'/posts.json'
    terms = sources.queries(query)
    counts = {term: 0 for term in terms}
    now = window_end or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('采集窗口必须包含时区')
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    since = now-timedelta(days=days)
    robots_response = public_get(source, base+'/robots.txt')
    if robots_response.text.lstrip('\ufeff \t\r\n').startswith('<'):
        raise ValueError('社区robots返回HTML/XML页面，无法确认访问规则，未采集')
    robots = RobotFileParser()
    robots.parse(robots_response.text.splitlines())
    if not robots.can_fetch(USER_AGENT, endpoint):
        raise ValueError('社区robots规则不允许读取帖子接口，未采集')
    rows, pages, seen = [], [], set()
    before = None
    stop_reason = 'scan_limit'
    error = None
    scanned = 0
    skipped = 0
    for _ in range(MAX_PAGES):
        params = {'before': before} if before is not None else {}
        try:
            posts = public_get(source, endpoint, params).json()['latest_posts']
            if not isinstance(posts, list):
                raise ValueError('社区帖子响应格式异常')
            ids = [p['id'] for p in posts]
            if any(type(i) is not int or i <= 0 for i in ids):
                raise ValueError('社区帖子编号异常')
            if before is not None and any(i >= before for i in ids):
                raise ValueError('社区分页游标未前进，停止重复采集')
            pages.append({'endpoint': endpoint, 'params': params,
                          'retrieved_at': datetime.now(timezone.utc).isoformat(), 'returned_count': len(posts)})
            if not posts:
                stop_reason = 'feed_exhausted'
                break
            scanned += len(posts)
            for p in posts:
                if p['id'] in seen:
                    continue
                seen.add(p['id'])
                try:
                    if not isinstance(p.get('created_at'), str):
                        raise ValueError('invalid publication date')
                    published = datetime.fromisoformat(p['created_at'].replace('Z', '+00:00'))
                    if published.tzinfo is None:
                        raise ValueError('missing timezone')
                    if not since <= published <= now:
                        continue
                    if type(p['topic_id']) is not int or type(p['post_number']) is not int or min(p['topic_id'], p['post_number']) <= 0:
                        raise ValueError('invalid topic')
                    title = sources.redact(sources.plain_html(p['topic_title']))
                    body = sources.redact(sources.plain_html(p['cooked']))
                    if not body.strip():
                        raise ValueError('missing body')
                except (KeyError, TypeError, ValueError):
                    skipped += 1
                    continue
                content = (title+' '+body).casefold()
                matches = [t for t in terms if sources.matches_local_query(content,t)]
                if not matches:
                    continue
                reads = p.get('reads')
                reads = reads if type(reads) is int and reads >= 0 else None
                replies = p.get('reply_count')
                replies = replies if type(replies) is int and replies >= 0 else None
                rows.append(dict(title=title, raw_text=body,
                    url=f"{base}/t/{p['topic_id']}/{p['post_number']}",
                    published_at=p['created_at'], updated_at=p.get('updated_at'), stars=None,
                    heat={'阅读计数': reads, '回复数': replies},
                    license='Node-RED/OpenJS非代码投稿：CC BY 4.0；代码内容另依项目/IP条款；须保留出处并核对原帖例外',
                    provenance={'item_type': 'topic' if p['post_number']==1 else 'reply',
                                'post_id': p['id'], 'topic_id': p['topic_id'], 'post_number': p['post_number'],
                                'body_available': True, 'body_method': 'API cooked正文转文本，未使用搜索摘要',
                                'matched_queries': matches, 'query_match_method':sources.LOCAL_QUERY_MATCH_VERSION, 'retrieval_endpoint': endpoint},
                    reliability={'origin': '产品官方社区的用户投稿', 'transport': 'HTTPS直接读取原站公开接口',
                                 'terms_url': base+'/tos', 'terms_reviewed_on': source_policy.REVIEWED_ON,
                                 'content_verified': False, 'note': '原站可追溯；用户陈述未经独立证实，回复可能依赖上下文',
                                 'retained_body_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest()}))
                rows[-1]['provenance']['list_body_truncated'] = p.get('truncated') is not False
            before = min(ids)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            stop_reason = 'error'
            break
    # Rank only the bounded scanned sample; never claim these are site-wide top posts.
    rows.sort(key=lambda r: (r['heat']['阅读计数'] is not None, r['heat']['阅读计数'] or 0, r['heat']['回复数'] or 0,
                             r['published_at'], r['provenance']['post_id']), reverse=True)
    candidates = len(rows)
    selected = []
    detail_requests = []
    for row in rows:
        eligible = [t for t in row['provenance']['matched_queries'] if counts[t] < limit]
        if not eligible:
            continue
        if row['provenance']['list_body_truncated']:
            if len(detail_requests) >= MAX_DETAIL_REQUESTS:
                error = '已达单条正文请求保护上限，请减少每来源条数或检索词后重新采集'
                stop_reason = 'detail_limit'
                break
            detail_url = base+f"/posts/{row['provenance']['post_id']}.json"
            try:
                if not robots.can_fetch(USER_AGENT, detail_url):
                    raise ValueError('robots不允许读取单条帖子正文')
                detail_requests.append({'endpoint': detail_url, 'retrieved_at': datetime.now(timezone.utc).isoformat()})
                full = public_get(source, detail_url).json()
                if any(full.get(k) != row['provenance'][out] for k,out in
                       (('id','post_id'),('topic_id','topic_id'),('post_number','post_number'))):
                    raise ValueError('单条正文与列表帖子的身份不一致')
                if full.get('truncated') or not isinstance(full.get('cooked'), str):
                    raise ValueError('单条帖子正文仍不完整')
                body = sources.redact(sources.plain_html(full['cooked']))
                if not body.strip():
                    raise ValueError('单条帖子正文为空')
                row['raw_text'] = body
                row['updated_at'] = full.get('updated_at')
                row['reliability']['retained_body_sha256'] = hashlib.sha256(body.encode('utf-8')).hexdigest()
                row['provenance'].update(retrieval_endpoint=detail_url, list_endpoint=endpoint,
                                         body_method='单条帖子API cooked正文转文本；身份核对通过，未使用列表摘要')
                content = (row['title']+' '+body).casefold()
                eligible = [t for t in eligible if sources.matches_local_query(content,t)]
                if not eligible:
                    continue
            except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                stop_reason = 'detail_error'
                break
        row['provenance']['body_complete_verified'] = True
        row['provenance']['selection_queries'] = eligible
        for term in eligible:
            counts[term] += 1
        selected.append(row)
    rows = selected
    return rows, {'pages': pages, 'complete': error is None, 'error': error,
                  'window_start': since.isoformat(), 'window_end': now.isoformat(),
                  'returned_count': len(rows), 'scanned_posts': scanned, 'skipped_invalid_posts': skipped,
                  'matched_before_ranking': candidates,
                  'detail_requests': detail_requests, 'max_detail_requests': MAX_DETAIL_REQUESTS,
                  'ranking_method': '扫描样本内按已知阅读计数降序；未知热度排后；同分按回复数、发布时间、帖子编号降序。不代表全站热门。',
                  'matched_counts': counts, 'stop_reason': stop_reason, 'coverage_limited': True,
                  'robots_url': base+'/robots.txt',
                  'query_match_method':sources.LOCAL_QUERY_MATCH_VERSION,
                  'scope': f'近期公开帖子最多扫描{MAX_PAGES}页；本次扫描{scanned}条，按关键词各词同时匹配并按样本阅读计数选取；不是全站历史搜索或全站热门排名，未命中不代表没有需求'}
