from datetime import datetime,timezone,timedelta
from unittest.mock import patch,Mock
import app
import sources
from test_pipeline import client,source_fixture


def test_all_sources_in_batch_use_batch_start_as_fixed_window(client):
    windows=[]
    def fetch(source,query,limit,days,window_end=None):
        windows.append(window_end)
        return source_fixture(source,query,limit,days)
    with patch.object(app.sources,'fetch',side_effect=fetch):
        r=client.post('/api/batches',json={'direction':'办公自动化','query':'test',
                                          'sources':['github','stackoverflow']})
    data=client.get('/api/batches/'+r.json()['id']).json()
    expected=datetime.fromisoformat(data['batch']['created_at']).replace(microsecond=0)
    assert windows==[expected,expected]


def test_every_page_and_query_uses_the_same_snapshot():
    snapshot=datetime(2026,1,1,tzinfo=timezone.utc)
    received=[]
    def page(source,query,limit,days,page,window_end=None):
        received.append(window_end)
        return [],{'total_count':200,'has_more':None}
    with patch.object(sources,'fetch_page',side_effect=page),patch.object(sources,'_cooldown',{}):
        _,meta=sources.fetch('github','first\nsecond',200,365,window_end=snapshot)
    assert received==[snapshot]*4
    assert meta['window_end']==snapshot.isoformat()


def test_stackexchange_page_uses_fixed_query_window_and_real_retrieval_time():
    snapshot=datetime(2025,1,10,tzinfo=timezone.utc)
    response=Mock(status_code=200,headers={})
    response.json.return_value={'items':[],'has_more':False}
    with patch.object(sources.requests,'get',return_value=response) as get,patch.object(sources,'_cooldown',{}):
        _,meta=sources.fetch_page('superuser','test',10,30,window_end=snapshot)
    params=get.call_args.kwargs['params']
    assert params['todate']==int(snapshot.timestamp())
    assert params['fromdate']==int((snapshot-timedelta(days=30)).timestamp())
    assert datetime.fromisoformat(meta['retrieved_at'])>snapshot


def test_github_window_converts_offset_to_utc_before_formatting():
    snapshot=datetime(2025,1,10,8,tzinfo=timezone(timedelta(hours=8)))
    response=Mock(status_code=200,headers={})
    response.json.return_value={'items':[],'total_count':0}
    with patch.object(sources.requests,'get',return_value=response) as get,patch.object(sources,'_cooldown',{}):
        _,meta=sources.fetch_page('github_issues','test',10,1,window_end=snapshot)
    assert 'created:2025-01-09T00:00:00Z..2025-01-10T00:00:00Z' in get.call_args.kwargs['params']['q']
    assert datetime.fromisoformat(meta['retrieved_at'])>snapshot


def test_failed_source_still_records_requested_window(client):
    with patch.object(app.sources,'fetch',side_effect=ValueError('synthetic failure')):
        response=client.post('/api/batches',json={'direction':'办公自动化','query':'test','sources':['github']})
    data=client.get('/api/batches/'+response.json()['id']).json()
    import json
    metadata=json.loads(data['sources'][0]['metadata'])
    assert metadata['window_end']==datetime.fromisoformat(data['batch']['created_at']).replace(microsecond=0).isoformat()


def test_fractional_seconds_are_normalized_across_sources():
    snapshot=datetime(2025,1,10,8,0,0,987654,tzinfo=timezone(timedelta(hours=8)))
    response=Mock(status_code=200,headers={})
    response.json.return_value={'items':[],'total_count':0}
    with patch.object(sources.requests,'get',return_value=response) as get,patch.object(sources,'_cooldown',{}):
        _,meta=sources.fetch('github','test',10,1,window_end=snapshot)
    assert meta['window_end']=='2025-01-10T00:00:00+00:00'
    assert 'pushed:2025-01-09T00:00:00Z..2025-01-10T00:00:00Z' in get.call_args.kwargs['params']['q']


def test_forum_respects_second_precision_cutoff():
    import forum_sources
    snapshot=datetime(2025,1,10,0,0,0,987654,tzinfo=timezone.utc)
    def post(pid,created):
        return {'id':pid,'topic_id':pid,'post_number':1,'topic_title':'email',
                'cooked':'email evidence','created_at':created,'truncated':False}
    policy=Mock(text='User-agent: *\nDisallow: /search\n')
    first=Mock();first.json.return_value={'latest_posts':[
        post(2,'2025-01-10T00:00:00.500Z'),post(1,'2025-01-09T23:59:59.999Z')]}
    end=Mock();end.json.return_value={'latest_posts':[]}
    with patch.object(forum_sources,'public_get',side_effect=[policy,first,end]):
        rows,meta=forum_sources.fetch_forum('nodered','email',10,1,window_end=snapshot)
    assert [r['provenance']['post_id'] for r in rows]==[1]
    assert meta['window_end']=='2025-01-10T00:00:00+00:00'
