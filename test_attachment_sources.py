"""Synthetic source responses; never represented as collected research data."""
from datetime import datetime,timezone
from unittest.mock import patch
import json
import pytest
import extended_sources as adapter
import sources
import local_analysis
from local_routes import LocalConfig

NOW=datetime(2026,11,16,tzinfo=timezone.utc)


def dataset(**changes):
    return {'title':'AI invoice dataset','subtitle':'Our team needs AI invoice extraction using an OCR model API.',
            'description':'Example resource','url':'https://www.kaggle.com/datasets/example/invoices',
            'isPrivate':False,'lastUpdated':'2026-11-15T12:00:00Z','licenseName':'CC0',
            'ownerName':'MUST_NOT_PERSIST','creatorUrl':'MUST_NOT_PERSIST',**changes}


def test_kaggle_metadata_preserves_date_basis_and_excludes_private_data():
    payload=[dataset(),dataset(isPrivate=True),dataset(url='https://localhost/datasets/example/invoices')]
    with patch.object(adapter,'check_robots',return_value={'allowed':True}),patch.object(adapter,'get',return_value=(json.dumps(payload).encode(),200)) as get:
        rows,meta=sources.fetch('kaggle','invoice',20,30,window_end=NOW)
    assert len(rows)==1 and not meta['complete'] and meta['invalid_count']==2
    row=rows[0];assert row['published_at'] is None and row['updated_at']=='2026-11-15T12:00:00+00:00'
    assert row['provenance']['date_basis']=='dataset.lastUpdated'
    assert 'MUST_NOT_PERSIST' not in json.dumps(rows)
    assert 'pageSize' not in get.call_args.args[0]
    record={**row,'id':'S1','content':row['title']+'\n'+row['raw_text'],'metadata':{'provenance':row['provenance']}}
    assert not local_analysis.judge(record,'企业办公自动化',LocalConfig().model_dump())['opportunity']


def test_kaggle_retains_completed_page_when_later_page_fails():
    with patch.object(adapter,'check_robots',return_value={'allowed':True}),patch.object(adapter,'get',side_effect=[(json.dumps([dataset()]*20).encode(),200),ValueError('HTTP 429')]):
        rows,meta=sources.fetch('kaggle','invoice',20,30,window_end=NOW)
    assert len(rows)==1 and len(meta['pages'])==1 and not meta['complete']
    assert '429' in meta['error']


@pytest.mark.parametrize('prefix',['0','1'])
def test_ithome_rss_is_excerpt_not_scraped_article(prefix):
    payload=('<rss><channel><item><title>AI office</title><link>https://www.ithome.com/'+prefix+'/999/123.htm</link><description>&lt;p&gt;AI workflow report&lt;/p&gt;</description><pubDate>Sun, 15 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>').encode()
    with patch.object(adapter,'check_robots',return_value={'allowed':True}),patch.object(adapter,'get',return_value=(payload,200)) as get:
        rows,meta=sources.fetch('ithome','AI',20,30,window_end=NOW)
    assert len(rows)==1 and get.call_count==1
    assert rows[0]['provenance']['content_kind']=='news_excerpt'
    assert rows[0]['provenance']['evidence_role']=='secondary_report'
    assert meta['coverage_limited'] and meta['complete']


def test_html_challenge_is_not_a_permissive_robots_file():
    adapter._robots.clear()
    with patch.object(adapter,'get',return_value=(b'<!DOCTYPE html><html>Verify your browser</html>',200)):
        with pytest.raises(ValueError,match='HTML'):
            adapter.check_robots('ithome')
    adapter._robots.clear()


def test_new_attachment_sources_are_accepted_by_batch_schema():
    from app import BatchInput
    assert BatchInput(direction='office',query='AI',sources=['ithome','kaggle']).sources==['ithome','kaggle']


def test_all_attachment_platforms_have_distinct_honest_catalog_status():
    import source_catalog
    report=source_catalog.report();entries=report['entries']
    assert len(entries)==len({row['id'] for row in entries})==20
    assert {row['id'] for row in entries if row['status']=='enabled'}=={'github','stackoverflow','v2ex','ithome','kaggle','producthunt','infoq','qbitai'}
    assert all(row['note'] and row['evidence_url'].startswith('https://') for row in entries)
    assert next(row for row in entries if row['id']=='paperswithcode')['status']=='redirected'


def product(**changes):
    return {'name':'Example','tagline':'Our team needs invoice automation','description':'An AI invoice extraction tool.',
            'url':'https://www.producthunt.com/products/example?ref=mcp','launched_at':'2026-11-15T12:00:00Z',
            'makers':[{'name':'MUST_NOT_PERSIST'}],'reviews_summary':'MUST_NOT_PERSIST',**changes}


def test_producthunt_public_tool_caps_dates_and_excludes_review_and_account_fields():
    with patch.object(adapter,'producthunt_search',return_value=[product(),product(url='https://localhost/products/example'),product(launched_at='2024-01-01T00:00:00Z')]) as search:
        rows,meta=sources.fetch('producthunt','invoice',100,730,window_end=NOW)
    assert search.call_args.args[0]=={'query':'invoice','limit':8,'days_ago':365}
    assert len(rows)==1 and not meta['complete'] and meta['invalid_count']==1 and meta['outside_window_count']==1
    assert rows[0]['url']=='https://www.producthunt.com/products/example'
    assert rows[0]['provenance']['evidence_role']=='technical_context'
    assert 'MUST_NOT_PERSIST' not in json.dumps(rows)
    from app import BatchInput
    assert BatchInput(direction='office',query='AI',sources=['producthunt']).sources==['producthunt']


def test_producthunt_retains_first_query_when_next_requires_authorization():
    with patch.object(adapter,'producthunt_search',side_effect=[[product()],ValueError('HTTP 401')]):
        rows,meta=sources.fetch('producthunt','invoice\nmeeting',10,30,window_end=NOW)
    assert len(rows)==1 and not meta['complete'] and '401' in meta['error']


def test_producthunt_transport_uses_only_read_tool_and_rejects_unstructured_output():
    from unittest.mock import MagicMock
    response=MagicMock();response.__enter__.return_value=response;response.status_code=200
    response.iter_content.return_value=[json.dumps({'result':{'content':[{'type':'text','text':'not original evidence'}]}}).encode()]
    adapter._next.pop('producthunt',None)
    with patch.object(adapter.requests,'post',return_value=response) as post:
        with pytest.raises(ValueError,match='结构化'):
            adapter.producthunt_search({'query':'invoice','days_ago':30,'limit':3})
    body=post.call_args.kwargs['json']
    assert body['method']=='tools/call' and body['params']['name']=='search_launches'
    assert 'Authorization' not in post.call_args.kwargs['headers']
    adapter._next.pop('producthunt',None)


@pytest.mark.parametrize('key,url',[('infoq','https://www.infoq.cn/article/AbCd123?utm_source=rss'),('qbitai','https://www.qbitai.com/2026/11/123456.html')])
def test_media_feeds_retain_only_declared_description(key,url):
    payload=('<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><title>AI meeting</title><link>'+url+'</link><description>&lt;p&gt;Short summary&lt;/p&gt;</description><content:encoded>FULL_ARTICLE_MUST_NOT_PERSIST</content:encoded><pubDate>Sun, 15 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>').encode()
    with patch.object(adapter,'check_robots',return_value={'allowed':True}),patch.object(adapter,'get',return_value=(payload,200)) as get:
        rows,meta=sources.fetch(key,'AI',20,30,window_end=NOW)
    assert len(rows)==1 and rows[0]['raw_text']=='Short summary' and meta['complete']
    assert 'FULL_ARTICLE_MUST_NOT_PERSIST' not in json.dumps(rows)
    assert rows[0]['provenance']['evidence_role']=='secondary_report' and get.call_count==1
    assert '?' not in rows[0]['url']


def test_infoq_link_only_description_is_not_body_or_demand_evidence():
    payload=('<rss><channel><item><title>Our team needs AI meeting transcription via Whisper model API</title><link>https://www.infoq.cn/article/example</link><description>&lt;div&gt;&lt;a href="https://www.infoq.cn/article/example"&gt;点击查看原文&gt;&lt;/a&gt;&lt;/div&gt;</description><pubDate>Sun, 15 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>').encode()
    with patch.object(adapter,'check_robots',return_value={'allowed':True}),patch.object(adapter,'get',return_value=(payload,200)):
        rows,meta=sources.fetch('infoq','AI',10,30,window_end=NOW)
    row=rows[0]
    assert row['raw_text']=='' and not row['provenance']['body_available']
    assert row['provenance']['content_kind']=='news_headline' and row['provenance']['evidence_role']=='technical_context'
    record={**row,'id':'S1','content':row['title'],'metadata':{'provenance':row['provenance']}}
    assert not local_analysis.judge(record,'企业办公自动化',LocalConfig().model_dump())['opportunity']


def test_feed_invalid_port_is_counted_without_losing_other_valid_entries():
    item='<item><title>AI</title><link>{}</link><pubDate>Sun, 15 Nov 2026 12:00:00 GMT</pubDate></item>'
    payload=('<rss><channel>'+item.format('https://www.infoq.cn:invalid/article/x')+item.format('https://www.infoq.cn/article/y')+'</channel></rss>').encode()
    with patch.object(adapter,'check_robots',return_value={'allowed':True}),patch.object(adapter,'get',return_value=(payload,200)):
        rows,meta=sources.fetch('infoq','AI',10,30,window_end=NOW)
    assert len(rows)==1 and meta['invalid_count']==1 and not meta['complete']
