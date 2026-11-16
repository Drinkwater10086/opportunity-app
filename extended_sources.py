"""Reviewed, bounded public feeds: V2EX JSON and arXiv RSS/Atom metadata.

V2EX is listed in contest attachment 2. arXiv extends its academic category.
No arbitrary target URLs, author profiles, comments, or full paper downloads.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
import content_formats

SOURCES = {
    'v2ex': {'name':'V2EX','endpoint':'https://www.v2ex.com/api/topics/latest.json',
             'robots':'https://www.v2ex.com/robots.txt', 'hosts':('www.v2ex.com','v2ex.com'),
             'terms':'https://www.v2ex.com/about', 'interval':10,
             'scope':'仅公开latest接口当前返回主题，按检索词本地筛选；不是全站历史搜索'},
    'arxiv': {'name':'arXiv','endpoint':'https://rss.arxiv.org/rss/cs.AI',
              'robots':'https://rss.arxiv.org/robots.txt', 'hosts':('arxiv.org','www.arxiv.org'),
              'terms':'https://info.arxiv.org/help/api/tou.html', 'interval':3,
              'scope':'仅cs.AI当日RSS/Atom摘要；周末或无更新时可能为空，不覆盖整个历史窗口'},
    'ithome': {'name':'IT之家','endpoint':'https://www.ithome.com/rss/',
               'robots':'https://www.ithome.com/robots.txt','hosts':('www.ithome.com',),
               'terms':'https://www.ithome.com/0/000/037.htm','interval':3,
               'path_pattern':r'/\d+/\d{3}/\d{3}\.htm',
               'scope':'仅官方RSS当前条目的标题和订阅摘要，不补抓文章、评论或图片，不是历史全文搜索',
               'content_kind':'news_excerpt','evidence_role':'secondary_report',
               'reliability_note':'媒体订阅摘要是二手报道，未经独立核实；不等于用户亲述或全文',
               'body_method':'官方RSS提供摘要，未补抓全文；媒体转述未经独立核实',
               'license':'IT之家原文版权归权利人；官方RSS订阅不等于可任意转载全文',
               'policy_reviewed_on':'2026-11-16'},
    'kaggle': {'name':'Kaggle','endpoint':'https://www.kaggle.com/api/v1/datasets/list',
               'robots':'https://www.kaggle.com/robots.txt','hosts':('www.kaggle.com',),
               'terms':'https://www.kaggle.com/terms','interval':2,
               'scope':'公开数据集目录元数据，每组最多扫描3页；按最近更新时间过滤，不下载数据文件'},
    'producthunt': {'name':'Product Hunt','endpoint':'https://mcp.producthunt.com/mcp',
                    'terms':'https://www.producthunt.com/legal','interval':3,
                    'scope':'官方noauth只读search_launches；每组最多8项、最多近365天；名称/标语字面搜索，不取评论、账户或发布功能'},
}
_lock = threading.Lock()
_next = {}
_robots = {}
UA = 'OpportunityResearch/1.0 (+https://github.com/Drinkwater10086/opportunity-app)'


def get(url, key, allow_missing=False):
    with _lock:
        wait = _next.get(key, 0)-time.monotonic()
        if wait > 30:
            raise ValueError('来源处于限流冷却期，请稍后重试')
        if wait > 0: time.sleep(wait)
        _next[key] = time.monotonic()+SOURCES[key]['interval']
        with requests.get(url, headers={'User-Agent':UA}, timeout=(10,30),
                          allow_redirects=False, stream=True) as response:
            if allow_missing and response.status_code == 404:
                return b'', 404
            if response.status_code == 429:
                try: seconds=float(response.headers.get('Retry-After','60'))
                except ValueError: seconds=60
                _next[key]=time.monotonic()+max(60,min(seconds,3600))
            if response.status_code != 200:
                raise ValueError(f'来源HTTP {response.status_code}，未绕过限制或自动追踪重定向')
            data=bytearray()
            for part in response.iter_content(65536):
                data.extend(part)
                if len(data)>4_000_000: raise ValueError('来源响应超过4MB，未截断')
            return bytes(data), 200


def check_robots(key):
    cfg=SOURCES[key]
    cached=_robots.get(key)
    if cached and time.monotonic()-cached['checked_monotonic']<21600:
        return {k:v for k,v in cached.items() if k!='checked_monotonic'}
    data,status=get(cfg['robots'],key,allow_missing=True)
    allowed=status==404
    if status==200:
        # A challenge page is not a permissive robots file.
        if re.search(br'<(?:!doctype|html|head|body|script)\b',data[:10000],re.I):
            raise ValueError('robots.txt返回HTML验证页，未将其视为允许采集')
        parser=RobotFileParser();parser.parse(data.decode('utf-8').splitlines())
        allowed=parser.can_fetch(UA,cfg['endpoint'])
    if not allowed: raise ValueError('robots.txt禁止此采集路径，来源未采集')
    snapshot={'url':cfg['robots'],'status':status,'sha256':hashlib.sha256(data).hexdigest(),
              'checked_at':datetime.now(timezone.utc).isoformat(),'allowed':allowed,
              'checked_monotonic':time.monotonic()}
    _robots[key]=snapshot
    return {k:v for k,v in snapshot.items() if k!='checked_monotonic'}


def producthunt_search(arguments):
    """Only the verified public read tool; never accept caller-supplied tool names."""
    key='producthunt';cfg=SOURCES[key]
    with _lock:
        wait=_next.get(key,0)-time.monotonic()
        if wait>30:raise ValueError('Product Hunt限流冷却中，请稍后重试')
        if wait>0:time.sleep(wait)
        _next[key]=time.monotonic()+cfg['interval']
        with requests.post(cfg['endpoint'],json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                           'params':{'name':'search_launches','arguments':arguments}},
                           headers={'User-Agent':UA,'Accept':'application/json, text/event-stream'},
                           timeout=(10,30),allow_redirects=False,stream=True) as response:
            if response.status_code==429:
                try:seconds=float(response.headers.get('Retry-After','60'))
                except ValueError:seconds=60
                _next[key]=time.monotonic()+max(60,min(seconds,3600))
            if response.status_code!=200:raise ValueError(f'Product Hunt HTTP {response.status_code}，未自动重试或请求账户权限')
            data=bytearray()
            for part in response.iter_content(65536):
                data.extend(part)
                if len(data)>4_000_000:raise ValueError('Product Hunt响应超过4MB，未截断')
            envelope=json.loads(data)
    if not isinstance(envelope,dict) or envelope.get('error'):raise ValueError('Product Hunt RPC失败')
    result=envelope.get('result')
    if not isinstance(result,dict) or result.get('isError'):raise ValueError('Product Hunt搜索失败或需要授权；未自动升级权限')
    structured=result.get('structuredContent')
    if not isinstance(structured,dict) or structured.get('status')!='ok':raise ValueError('Product Hunt缺少有效结构化搜索结果')
    payload=structured.get('data')
    if not isinstance(payload,dict) or not isinstance(payload.get('products'),list):raise ValueError('Product Hunt产品列表无效')
    return payload['products']


def parsed_date(value):
    if isinstance(value,str):
        try: dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError: dt=parsedate_to_datetime(value)
    elif type(value) in (float,int):dt=datetime.fromtimestamp(value,timezone.utc)
    else: raise ValueError('缺失发布时间')
    if dt.tzinfo is None:raise ValueError('发布时间缺少时区')
    return dt.astimezone(timezone.utc)


def fetch(key, query, limit, days, window_end):
    import sources  # defer to avoid adapter import cycle
    cfg=SOURCES[key]
    if key=='producthunt':
        from resource_sources import fetch_producthunt
        return fetch_producthunt(query,limit,days,window_end)
    search=sources.queries(query); robots=check_robots(key)
    if key=='kaggle':
        from resource_sources import fetch_kaggle
        return fetch_kaggle(query,limit,days,window_end,robots)
    data,_=get(cfg['endpoint'],key)
    if key=='v2ex':
        payload=json.loads(data)
        if not isinstance(payload,list):raise ValueError('V2EX响应不是主题列表')
        items=[]
        for item in payload:
            if not isinstance(item,dict):raise ValueError('V2EX主题字段无效')
            if item.get('deleted'):continue
            plain=item.get('content')
            items.append({'title':item.get('title',''),'url':item.get('url',''),
                          'body':plain if isinstance(plain,str) and plain.strip() else item.get('content_rendered',''),
                          'body_format':'markdown' if isinstance(plain,str) and plain.strip() else 'html',
                          'published':item.get('created'),'updated':item.get('last_modified'),
                          'heat':{'回复数':item.get('replies')}, 'date_basis':'topic.created'})
        transport='json'
    else:items,transport=content_formats.feed_entries(data)
    records=[];invalid=0;outside=0;counts={term:0 for term in search};seen=set()
    for item in items:
        title=sources.redact(content_formats.text(item['title'],'html'))
        raw=sources.redact(content_formats.text(item.get('body') or '',item['body_format']))
        combined=title+'\n'+raw
        matched=[term for term in search if sources.matches_local_query(combined,term)]
        if not matched:continue
        try:
            published=parsed_date(item['published'])
            updated=parsed_date(item['updated']).isoformat() if item.get('updated') else None
        except (ValueError,TypeError,OverflowError):invalid+=1;continue
        if not window_end-timedelta(days=days)<=published<=window_end:
            outside+=1;continue
        url=urlparse(item['url'])
        if url.hostname not in cfg['hosts'] or url.scheme not in ('http','https') or url.username or url.password or url.port not in (None,80,443):
            invalid+=1;continue
        path_ok = re.fullmatch(cfg.get('path_pattern',r'/t/\d+' if key=='v2ex' else r'/abs/(?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?'),url.path)
        if not path_ok:invalid+=1;continue
        canonical='https://'+url.hostname+url.path
        if canonical in seen or all(counts[t]>=limit for t in matched):continue
        seen.add(canonical)
        for t in matched:counts[t]+=1
        records.append({'title':title,'raw_text':raw,'url':canonical,'published_at':published.isoformat(),
                        'updated_at':updated,'stars':None,'heat':item.get('heat',{}),
                        'license':cfg.get('license','arXiv描述性元数据CC0 1.0；不含论文全文' if key=='arxiv' else '原帖权利归作者；公开接口可读不代表可任意转载'),
                        'provenance':{'body_available':bool(raw),'body_method':cfg.get('body_method','论文摘要，未获取全文' if key=='arxiv' else '公开主题正文，未采集回复或成员资料'),
                                      'transport_format':transport,'content_format':item['body_format'],
                                      'content_kind':cfg.get('content_kind','abstract' if key=='arxiv' else 'discussion'),
                                      'evidence_role':cfg.get('evidence_role','technical_context' if key=='arxiv' else 'demand_signal'),
                                      'date_basis':item['date_basis'],'matched_queries':matched,'query_match_method':sources.LOCAL_QUERY_MATCH_VERSION},
                        'reliability':{'origin':cfg['name'],'note':cfg.get('reliability_note','论文摘要只用于技术背景，不单独作为需求机会证据' if key=='arxiv' else '社区自述未经独立核实'),
                                       'retained_body_sha256':hashlib.sha256(raw.encode()).hexdigest()}})
    return records, {'complete':invalid==0,'error':'存在日期或链接异常，已跳过并标记部分完成' if invalid else '',
                     'endpoint':cfg['endpoint'],'retrieved_at':datetime.now(timezone.utc).isoformat(),
                     'scope':cfg['scope'],'coverage_limited':True,'scanned_count':len(items),'query_match_method':sources.LOCAL_QUERY_MATCH_VERSION,
                     'returned_count':len(records),'invalid_count':invalid,'outside_window_count':outside,
                     'window_start':(window_end-timedelta(days=days)).isoformat(),'window_end':window_end.isoformat(),
                     'robots':robots,'terms_url':cfg['terms'],'policy_reviewed_on':cfg.get('policy_reviewed_on','2026-11-14'),
                     'transport_format':transport,'query_matching':'各行OR，行内空白分词AND；不支持高级搜索运算符'}
