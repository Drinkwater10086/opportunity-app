from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest
import content_formats as formats
import extended_sources as adapter
import sources
import local_analysis
from local_routes import LocalConfig

NOW=datetime(2026,11,14,tzinfo=timezone.utc)


def test_safe_formats_and_xml():
    assert formats.text('<p>Hello</p><script>secret()</script><p>world &amp; text</p>','html') == 'Hello\n\nworld & text'
    assert formats.text('# Heading\nbody','markdown') == '# Heading\nbody'
    assert formats.text('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello','vtt') == 'Hello'
    with pytest.raises(ValueError):formats.text('binary','pdf')
    with pytest.raises(ValueError):formats.feed_entries(b'<!DOCTYPE rss><rss/>')
    atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Test</title><link href="https://arxiv.org/abs/2611.12345"/><published>2026-11-13T00:00:00Z</published><summary type="html">&lt;p&gt;Hello&lt;/p&gt;</summary></entry></feed>'
    rows,kind=formats.feed_entries(atom)
    assert kind=='atom' and formats.text(rows[0]['body'],rows[0]['body_format'])=='Hello'


def fake_v2ex():
    return [{'title':'AI meeting problem','url':'https://www.v2ex.com/t/12345#reply0',
             'content':'Our team needs AI meeting transcription via a Whisper model API. Email test@example.com',
             'created':int(NOW.timestamp())-60,'last_modified':int(NOW.timestamp()),'replies':3,
             'member':{'username':'MUST_NOT_PERSIST'},'last_reply_by':'MUST_NOT_PERSIST'}]


def test_v2ex_schema_redaction_recent_scope():
    with patch.object(adapter,'check_robots',return_value={'allowed':True}), patch.object(adapter,'get',return_value=(json.dumps(fake_v2ex()).encode(),200)):
        rows,meta=sources.fetch('v2ex','AI meeting',20,30,window_end=NOW)
    assert len(rows)==1 and rows[0]['url']=='https://www.v2ex.com/t/12345'
    serialized=json.dumps(rows)
    assert 'MUST_NOT_PERSIST' not in serialized and 'test@example.com' not in serialized
    assert rows[0]['heat']['回复数']==3
    assert meta['coverage_limited'] and meta['complete'] and meta['transport_format']=='json'


def test_arxiv_rss_is_context_only_and_not_full_paper():
    rss=b'<rss version="2.0"><channel><item><title>AI meeting</title><link>https://arxiv.org/abs/2611.12345</link><description>Our team needs AI meeting transcription via Whisper model API.</description><pubDate>Fri, 13 Nov 2026 00:00:00 GMT</pubDate></item></channel></rss>'
    with patch.object(adapter,'check_robots',return_value={'allowed':True}), patch.object(adapter,'get',return_value=(rss,200)):
        rows,meta=sources.fetch('arxiv','AI meeting',20,30,window_end=NOW)
    assert len(rows)==1 and rows[0]['provenance']['content_kind']=='abstract'
    r={**rows[0],'id':'S1','content':rows[0]['raw_text'],'metadata':{'provenance':rows[0]['provenance']}}
    j=local_analysis.judge(r,'企业办公自动化',LocalConfig().model_dump())
    assert not j['opportunity'] and 'technical_context_only' in j['failed_checks']
    assert rows[0]['heat']=={} and rows[0]['stars'] is None


def test_missing_dates_malicious_links_and_empty_feed():
    rows=fake_v2ex();rows[0]['url']='https://localhost/t/12345'
    with patch.object(adapter,'check_robots',return_value={'allowed':True}), patch.object(adapter,'get',return_value=(json.dumps(rows).encode(),200)):
        records,meta=adapter.fetch('v2ex','AI meeting',10,30,NOW)
    assert not records and not meta['complete'] and meta['invalid_count']==1
    with patch.object(adapter,'check_robots',return_value={'allowed':True}), patch.object(adapter,'get',return_value=(b'<rss><channel/></rss>',200)):
        records,meta=adapter.fetch('arxiv','AI',10,30,NOW)
    assert records==[] and meta['complete'] and meta['scanned_count']==0


def test_robots_denial_is_not_ignored():
    adapter._robots.clear()
    with patch.object(adapter,'get',return_value=(b'User-agent: *\nDisallow: /',200)):
        with pytest.raises(ValueError,match='robots'):
            adapter.check_robots('v2ex')
    adapter._robots.clear()


def test_source_enum_accepts_new_sources():
    from app import BatchInput
    item=BatchInput(direction='office',query='AI meeting',sources=['v2ex','arxiv'])
    assert item.sources==['v2ex','arxiv']
