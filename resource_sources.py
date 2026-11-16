"""Public Kaggle catalogue metadata only. No authentication or dataset files."""
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode,urlparse
import hashlib
import json
import re
import requests


def fetch_producthunt(query,limit,days,window_end):
    import sources
    import extended_sources as transport
    cfg=transport.SOURCES['producthunt'];records=[];pages=[];seen=set();invalid=outside=0;error=None
    for term in sources.queries(query):
        params={'query':term,'days_ago':min(days,365),'limit':min(limit,8)}
        try:
            items=transport.producthunt_search(params)
            pages.append({'endpoint':cfg['endpoint'],'tool':'search_launches','arguments':params,'returned_count':len(items)})
            for item in items:
                try:
                    if not isinstance(item,dict):raise ValueError('非对象')
                    url=urlparse(item.get('url',''));title=item.get('name');tagline=item.get('tagline');description=item.get('description')
                    date=transport.parsed_date(item.get('launched_at'))
                    if (url.scheme!='https' or url.hostname!='www.producthunt.com' or url.username or url.password
                        or url.port not in (None,443) or not re.fullmatch(r'/products/[a-zA-Z0-9_-]+',url.path)
                        or not isinstance(title,str) or not title.strip()
                        or not isinstance(tagline,str) or not isinstance(description,str)):
                        raise ValueError('产品元数据无效')
                except (ValueError,TypeError,OverflowError):
                    invalid+=1;continue
                if not window_end-timedelta(days=min(days,365))<=date<=window_end:
                    outside+=1;continue
                canonical='https://www.producthunt.com'+url.path
                if canonical in seen:continue
                seen.add(canonical)
                raw=sources.redact('\n\n'.join(x for x in (tagline,description) if x.strip()))
                records.append({'title':sources.redact(title),'raw_text':raw,'url':canonical,
                    'published_at':date.isoformat(),'updated_at':None,'stars':None,
                    'heat':{'投票数':item['votes_count']} if type(item.get('votes_count')) is int and item['votes_count']>=0 else {},
                    'license':'Product Hunt及内容权利人保留权利；仅非商业研究的有限产品资料，公开转载或商业使用须另行核对许可',
                    'provenance':{'body_available':bool(raw),'body_method':'官方只读产品搜索返回的标语和简介；不取评论、评价摘要、创始人或账户资料',
                                  'transport_format':'json-rpc','content_format':'text','content_kind':'product_metadata',
                                  'evidence_role':'technical_context','date_basis':'product.launched_at','matched_query':term,
                                  'search_semantics':'名称与标语字面搜索；非语义分析；单组最多8项，无分页，最多近365天',
                                  'auth_mode':'official_tool_noauth'},
                    'reliability':{'origin':'Product Hunt','note':'产品发布者简介是供给侧主张，未独立验证，不单独作为用户需求证据',
                                   'retained_body_sha256':hashlib.sha256(raw.encode('utf8')).hexdigest()}})
        except (ValueError,requests.RequestException) as exc:
            error=sources.redact(str(exc)) if isinstance(exc,ValueError) else type(exc).__name__
            break
    return records,{'complete':not error and invalid==0,'error':error or ('存在无效产品元数据，标记部分完成' if invalid else ''),
                    'pages':pages,'returned_count':len(records),'invalid_count':invalid,'outside_window_count':outside,
                    'scope':cfg['scope'],'coverage_limited':True,'per_query_result_cap':8,'effective_days':min(days,365),
                    'window_start':(window_end-timedelta(days=min(days,365))).isoformat(),'window_end':window_end.isoformat(),
                    'date_basis':'product.launched_at','terms_url':cfg['terms'],'auth_mode':'official_tool_noauth',
                    'policy_reviewed_on':'2026-11-16','retrieved_at':datetime.now(timezone.utc).isoformat()}


def fetch_kaggle(query,limit,days,window_end,robots):
    import sources
    import extended_sources as transport
    cfg=transport.SOURCES['kaggle'];records=[];seen=set();pages=[];invalid=outside=0;error=None
    for term in sources.queries(query):
        kept=0
        for page in range(1,4):
            params={'search':term,'page':page}
            try:
                data,_=transport.get(cfg['endpoint']+'?'+urlencode(params),'kaggle')
                payload=json.loads(data)
                if not isinstance(payload,list):raise ValueError('Kaggle目录响应不是列表')
                pages.append({'endpoint':cfg['endpoint'],'params':params,'returned_count':len(payload)})
                for item in payload:
                    if not isinstance(item,dict):raise ValueError('Kaggle目录项不是对象')
                    if item.get('isPrivate') is not False:
                        invalid+=1;continue
                    try:
                        url=urlparse(item.get('url',''))
                        date=transport.parsed_date(item.get('lastUpdated'))
                        title=item.get('title');subtitle=item.get('subtitle') or '';description=item.get('description') or ''
                        if (url.scheme!='https' or url.hostname!='www.kaggle.com' or url.username or url.password
                            or url.port not in (None,443) or not re.fullmatch(r'/datasets/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+',url.path)
                            or not isinstance(title,str) or not title.strip()
                            or not isinstance(subtitle,str) or not isinstance(description,str)):
                            raise ValueError('无效公开数据集元数据')
                    except (ValueError,TypeError,OverflowError):
                        invalid+=1;continue
                    if not window_end-timedelta(days=days)<=date<=window_end:
                        outside+=1;continue
                    canonical='https://www.kaggle.com'+url.path
                    if canonical in seen:continue
                    raw=sources.redact('\n\n'.join(x for x in (subtitle,description) if x.strip()))
                    records.append({'title':sources.redact(title),'raw_text':raw,'url':canonical,
                        'published_at':None,'updated_at':date.isoformat(),'stars':None,
                        'heat':{label:item[key] for key,label in [('downloadCount','下载数'),('voteCount','投票数')]
                                if type(item.get(key)) is int and item[key]>=0},
                        'license':'平台返回的数据集许可：'+str(item.get('licenseName') or '未提供')+'；仅留存目录描述，不含数据文件，元数据使用仍须符合Kaggle条款',
                        'provenance':{'body_available':bool(raw),'body_method':'公开目录副标题/描述；未下载文件、Notebook、评论或用户档案',
                                      'transport_format':'json','content_format':'markdown','content_kind':'dataset_metadata',
                                      'evidence_role':'technical_context','date_basis':'dataset.lastUpdated',
                                      'matched_query':term,'search_semantics':'平台公开搜索；不声称本地逐词AND匹配'},
                        'reliability':{'origin':'Kaggle','note':'数据集目录仅作技术资源，不单独当作用户需求；发布时间未知，不用更新时间冒充发布时间',
                                       'retained_body_sha256':hashlib.sha256(raw.encode('utf8')).hexdigest()}})
                    seen.add(canonical);kept+=1
                    if kept>=limit:break
                if kept>=limit or len(payload)<20:break
            except (ValueError,requests.RequestException) as exc:
                error=sources.redact(str(exc)) if isinstance(exc,ValueError) else type(exc).__name__
                break
        if error:break
    return records,{'complete':not error and invalid==0,'error':error or ('存在无效或非公开目录项，标记部分完成' if invalid else ''),
                    'pages':pages,'returned_count':len(records),'invalid_count':invalid,'outside_window_count':outside,
                    'coverage_limited':True,'scope':cfg['scope'],'per_query_page_cap':3,
                    'window_start':(window_end-timedelta(days=days)).isoformat(),'window_end':window_end.isoformat(),
                    'date_basis':'dataset.lastUpdated','robots':robots,'terms_url':cfg['terms'],
                    'policy_reviewed_on':'2026-11-16','retrieved_at':datetime.now(timezone.utc).isoformat()}
