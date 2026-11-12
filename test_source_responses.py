"""Malformed provider responses must fail closed without losing prior pages."""
from unittest.mock import Mock, patch
from datetime import datetime,timezone,timedelta
import pytest
import sources
import app
from test_pipeline import client
real_fetch = sources.fetch


def response(payload):
    r=Mock(status_code=200,headers={})
    r.json.return_value=payload
    return r


def github_item():
    return {'name':'Synthetic','description':'Example',
            'html_url':'https://github.com/example/synthetic',
            'created_at':'2026-01-01T00:00:00Z','pushed_at':'2026-01-02T00:00:00Z'}


@pytest.mark.parametrize('invalid',[[],None,'not-json-object',{'items':None},{'items':[None]}])
def test_invalid_second_page_preserves_first_page(invalid):
    first={'items':[github_item()],'total_count':200}
    with patch.object(sources,'_cooldown',{}), patch.object(sources.time,'sleep',side_effect=lambda *_: sources._cooldown.clear()), \
            patch.object(sources.requests,'get',side_effect=[response(first),response(invalid)]):
        rows,meta=sources.fetch('github','workflow',200,365)
    assert len(rows)==1 and not meta['complete'] and meta['error']
    assert len(meta['pages'])==1


def test_out_of_range_timestamp_is_a_handled_source_error():
    payload={'items':[{'title':'Example','link':'https://superuser.com/questions/1',
                       'creation_date':10**30}], 'has_more':False}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        rows,meta=sources.fetch('superuser','workflow',1,365)
    assert not rows and not meta['complete'] and meta['pages'][0]['invalid_date_count']==1


def test_invalid_result_count_does_not_mark_collection_success():
    payload={'items':[github_item()],'total_count':'two hundred'}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        with pytest.raises(ValueError,match='数量'):
            sources.fetch('github','workflow',200,365)


@pytest.mark.parametrize('source,payload',[
    ('github',{'items':[github_item()]}),
    ('stackoverflow',{'items':[]}),
])
def test_missing_pagination_metadata_is_not_marked_complete(source,payload):
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        with pytest.raises(ValueError,match='分页'):
            sources.fetch(source,'workflow',200,365)


@pytest.mark.parametrize('source,item,metadata',[
    ('github',{'name':'Example','html_url':'https://github.com/example/project', 'created_at':'2026-01-01T00:00:00Z','pushed_at':'2026-01-02T00:00:00Z'}, {'total_count':1}),
    ('github_issues',{'title':'Example','html_url':'https://github.com/example/project/issues/1','created_at':'2026-01-01T00:00:00Z'}, {'total_count':1}),
    ('superuser',{'title':'Example','link':'https://superuser.com/questions/1','body':None,'creation_date':int((datetime.now(timezone.utc)-timedelta(days=1)).timestamp())}, {'has_more':False}),
])
def test_missing_source_body_is_explicitly_marked(source,item,metadata):
    payload={'items':[item],**metadata}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        rows,_=sources.fetch(source,'workflow',1,365)
    assert rows[0]['raw_text']==''
    assert not rows[0]['provenance']['body_available']
    assert '仅' in rows[0]['provenance']['body_method']


def test_github_incomplete_results_preserve_returned_page_as_partial():
    payload={'items':[github_item()],'total_count':1,'incomplete_results':True}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        rows,meta=sources.fetch('github','workflow',100,365)
    assert len(rows)==1 and not meta['complete']
    assert meta['pages'][0]['incomplete_results'] is True
    assert '不完整' in meta['error']


def test_invalid_incomplete_flag_does_not_claim_success():
    payload={'items':[github_item()],'total_count':1,'incomplete_results':'false'}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        with pytest.raises(ValueError,match='完整性'):
            sources.fetch('github','workflow',100,365)


def test_incomplete_page_is_saved_in_partial_batch_and_not_analyzed(client):
    payload={'items':[github_item()],'total_count':1,'incomplete_results':True}
    with patch.object(sources,'_cooldown',{}),patch.object(app.sources,'fetch',side_effect=None,wraps=real_fetch), \
            patch.object(sources.requests,'get',return_value=response(payload)):
        created=client.post('/api/batches',json={'direction':'测试方向','query':'workflow','sources':['github']})
    bid=created.json()['id']
    data=client.get('/api/batches/'+bid).json()
    assert data['batch']['status']=='partial' and len(data['records'])==1
    assert data['sources'][0]['status']=='partial'
    assert client.get(f'/api/batches/{bid}/result1.csv').status_code==200
    assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==409
