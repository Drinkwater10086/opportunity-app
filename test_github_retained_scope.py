from datetime import datetime,timezone
from unittest.mock import Mock,patch
import hashlib
import pytest

import sources
import local_preprocessing
import local_analysis
from local_routes import LocalConfig


@pytest.mark.parametrize('query',['AI chatbot','"invoice extraction"','"in:comments" AI'])
def test_default_issue_scope_matches_retained_fields(query):
    effective,scope=sources.github_issue_search_scope(query)
    assert effective.endswith(' in:title,body')
    assert scope['mode']=='title_body_default' and not scope['comments_collected']


@pytest.mark.parametrize('query',['AI in:comments','AI in:title,body','AI IN:body'])
def test_explicit_user_scope_is_retained_with_body_only_caveat(query):
    effective,scope=sources.github_issue_search_scope(query)
    assert effective==query and scope['mode']=='user_qualified'
    assert '评论' in scope['note'] and not scope['comments_collected']


def test_issue_markdown_and_generic_types_are_not_parsed_as_html():
    body='Need help with List<T> and a <script>literal source</script> block.\n```python\nx = 1\n```'
    item={'title':'Example','body':body,'html_url':'https://github.com/example/project/issues/1',
          'created_at':'2026-11-14T00:00:00Z','updated_at':'2026-11-14T00:00:00Z','comments':2}
    response=Mock(status_code=200,headers={});response.json.return_value={'items':[item],'total_count':1}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response) as get:
        records,metadata=sources.fetch_page('github_issues','AI',10,30,window_end=datetime(2026,11,15,tzinfo=timezone.utc))
    row=records[0]
    assert row['raw_text']==body and 'List<T>' in row['raw_text']
    assert row['provenance']['content_format']=='markdown'
    assert row['reliability']['retained_body_sha256']==hashlib.sha256(body.encode()).hexdigest()
    assert metadata['search_scope']['mode']=='title_body_default'
    assert 'in:title,body' in get.call_args.kwargs['params']['q']


@pytest.mark.parametrize('wrapper',['<!--{}-->','<script>{}</script>','<STYLE>{}</STYLE>','<template>{}</template>'])
def test_hidden_markup_does_not_supply_demand_but_source_offsets_survive(wrapper):
    need='Our team needs AI meeting transcription using a Whisper model API.'
    raw=wrapper.format(need)
    structured=local_preprocessing.structure(raw)
    assert len(structured['text'])==len(raw)
    assert not structured['text'].strip()
    assert structured['excluded_spans'][0]['kind']=='html_hidden'
    row={'id':'S1','title':'Example','content':raw,'source':'test'}
    assert not local_analysis.judge(row,'企业办公自动化',LocalConfig().model_dump())['opportunity']
    original=raw+'\n\n'+need
    result=local_analysis.judge({**row,'content':original},'企业办公自动化',LocalConfig().model_dump())
    assert result['opportunity']
    assert result['selected_context']['start']>=len(raw)
    for span in result['evidence_spans'].values():
        if span:assert original[span['start']:span['end']]==span['text']


def test_hidden_html_inside_markdown_quote_is_masked_as_one_union():
    hidden='> <script>\nOur team needs AI meeting transcription using a Whisper model API.\n</script>'
    raw=hidden+'\n\nVisible List<T> remains.'
    structured=local_preprocessing.structure(raw)
    assert 'Our team needs' not in structured['text']
    assert 'List<T>' in structured['text']
    assert len(structured['text'])==len(raw)
    assert len(structured['excluded_spans'])==1
    assert structured['excluded_spans'][0]['kind']=='combined_hidden'
    assert structured['quality']['excluded_characters']==len(hidden)


def test_unclosed_html_example_inside_code_does_not_hide_following_prose():
    raw='```html\n<script>\n```\n\nOur team needs AI meeting transcription using a Whisper model API.'
    structured=local_preprocessing.structure(raw)
    assert 'Our team needs' in structured['text']
    result=local_analysis.judge({'id':'S1','title':'Example','content':raw,'source':'test'},'企业办公自动化',LocalConfig().model_dump())
    assert result['opportunity']
    hidden='<!--Our team needs AI extraction using an OCR model API.-->'
    structured=local_preprocessing.structure(raw+'\n\n'+hidden)
    assert 'Our team needs AI meeting' in structured['text']
    assert 'Our team needs AI extraction' not in structured['text']
