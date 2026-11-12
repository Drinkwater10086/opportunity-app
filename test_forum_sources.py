from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import hashlib
import pytest
import forum_sources as forums
import sources
import app
from test_pipeline import client


def post(pid=10, **overrides):
    return dict(id=pid, topic_id=100, post_number=1, topic_title='Email workflow',
                cooked='<p>I need email deduplication. test@example.com</p>',
                created_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), truncated=False, **overrides)


def reply(posts):
    r = Mock()
    r.json.return_value = {'latest_posts': posts}
    return r


def robots(text='User-agent: *\nDisallow: /search\n'):
    return Mock(text=text)


def test_forum_direct_body_limits_provenance_and_hash():
    with patch.object(forums, 'public_get', side_effect=[robots(),reply([post()]),reply([])]) as get:
        rows, meta = sources.fetch('nodered', 'email workflow\nemail', 1, 365)
    assert len(rows)==1 and meta['stop_reason']=='feed_exhausted'
    assert meta['matched_counts']=={'email workflow':1,'email':1}
    row=rows[0]
    assert row['url']=='https://discourse.nodered.org/t/100/1'
    assert 'test@example.com' not in row['raw_text'] and '<p>' not in row['raw_text']
    assert row['reliability']['retained_body_sha256']==hashlib.sha256(row['raw_text'].encode()).hexdigest()
    assert row['reliability']['content_verified'] is False
    assert all('/search' not in call.args[1] for call in get.call_args_list)


def test_robots_disallow_prevents_post_requests():
    with patch.object(forums,'public_get',return_value=robots('User-agent: *\nDisallow: /posts')) as get:
        with pytest.raises(ValueError,match='robots'):
            sources.fetch('nodered','email',2,365)
    assert get.call_count==1


def test_cursor_repetition_preserves_prior_page_and_marks_partial():
    with patch.object(forums,'public_get',side_effect=[robots(),reply([post()]),reply([post()])]) as get:
        rows,meta=sources.fetch('nodered','email',5,365)
    assert len(rows)==1 and not meta['complete'] and '游标' in meta['error']
    assert get.call_args.args[2]=={'before':10}


def test_time_window_and_missing_body_not_silently_admitted():
    old=post(9);old['created_at']='2000-01-01T00:00:00Z'
    empty=post(8);empty['cooked']=''
    with patch.object(forums,'public_get',side_effect=[robots(),reply([old,empty]),reply([])]):
        rows,meta=sources.fetch('nodered','email',2,365)
    assert rows==[] and meta['skipped_invalid_posts']==1 and meta['stop_reason']=='feed_exhausted'


def test_null_date_does_not_drop_valid_posts_or_leave_task_running():
    broken=post(9);broken['created_at']=None
    with patch.object(forums,'public_get',side_effect=[robots(),reply([post(),broken]),reply([])]):
        rows,meta=sources.fetch('nodered','email',5,365)
    assert len(rows)==1 and meta['skipped_invalid_posts']==1 and meta['complete']


def test_robots_html_error_page_is_not_treated_as_permission():
    with patch.object(forums,'public_get',side_effect=[robots('<!doctype html><html>Access denied</html>'),reply([])]) as get:
        with pytest.raises(ValueError,match='robots'):
            sources.fetch('nodered','email',1,365)
    assert get.call_count==1


def test_recent_scan_is_bounded_and_reports_limited_coverage():
    with patch.object(forums,'MAX_PAGES',2),patch.object(forums,'public_get',
            side_effect=[robots(),reply([post(10)]),reply([post(9)])]):
        rows,meta=sources.fetch('nodered','unmatched',5,365)
    assert not rows and meta['complete'] and meta['coverage_limited']
    assert meta['stop_reason']=='scan_limit' and meta['scanned_posts']==2


def test_redirect_does_not_follow_unverified_domain():
    with patch.object(sources,'_cooldown',{}),patch.object(forums.requests,'get',
            return_value=Mock(status_code=302)) as get:
        with pytest.raises(ValueError,match='重定向'):
            forums.public_get('nodered','https://discourse.nodered.org/posts.json')
    assert get.call_args.kwargs['allow_redirects'] is False


def test_rate_limit_preserves_previous_page_and_provider_cooldown():
    first=reply([post()]);first.status_code=200
    policy=robots();policy.status_code=200
    limited=Mock(status_code=429,headers={'Retry-After':'120'})
    with patch.object(sources,'_cooldown',{}),patch.object(forums.time,'sleep'), \
            patch.object(forums.requests,'get',side_effect=[policy,first,limited]) as get:
        rows,meta=sources.fetch('nodered','email',5,365)
        assert len(rows)==1 and not meta['complete'] and '限流' in meta['error']
        with pytest.raises(ValueError,match='冷却'):
            sources.fetch('nodered','email',5,365)
        assert get.call_count==3


def test_invalid_date_does_not_break_batch_or_other_sources(client):
    broken=post(9);broken['created_at']=None
    with patch.object(app.sources,'fetch',side_effect=None) as fetch,patch.object(forums,'public_get',
            side_effect=[robots(),reply([post(),broken]),reply([])]):
        fetch.return_value=forums.fetch_forum('nodered','email',5,365)
        response=client.post('/api/batches',json={'direction':'办公自动化','query':'email','sources':['nodered']})
    data=client.get('/api/batches/'+response.json()['id']).json()
    assert data['batch']['status']=='collected' and len(data['records'])==1
    import json
    assert json.loads(data['sources'][0]['metadata'])['skipped_invalid_posts']==1


def test_forum_metadata_survives_collection_and_export(client):
    with patch.object(app.sources,'fetch',side_effect=None) as fetch,patch.object(forums,'public_get',
            side_effect=[robots(),reply([post()]),reply([])]):
        fetch.return_value=forums.fetch_forum('nodered','email',1,365)
        r=client.post('/api/batches',json={'direction':'办公自动化','query':'email','limit':1,'sources':['nodered']})
    assert r.status_code==202
    bid=r.json()['id']
    data=client.get('/api/batches/'+bid).json()
    assert data['records'][0]['metadata']['reliability']['content_verified'] is False
    assert client.get(f'/api/batches/{bid}/evidence.json').status_code==200


def test_hotter_match_on_later_page_wins_over_first_match():
    newest=post(10,reads=1)
    older=post(9,reads=25)
    with patch.object(forums,'public_get',side_effect=[robots(),reply([newest]),reply([older]),reply([])]):
        rows,meta=sources.fetch('nodered','email',1,365)
    assert len(rows)==1 and rows[0]['provenance']['post_id']==9
    assert meta['matched_before_ranking']==2 and meta['matched_counts']['email']==1
    assert meta['coverage_limited'] and '全站' in meta['ranking_method']


@pytest.mark.parametrize('invalid',[None,-1,True,'1000'])
def test_unknown_or_invalid_heat_does_not_outrank_known_zero(invalid):
    bad=post(10,reads=invalid);zero=post(9,reads=0)
    with patch.object(forums,'public_get',side_effect=[robots(),reply([bad,zero]),reply([])]):
        rows,meta=sources.fetch('nodered','email',1,365)
    assert rows[0]['provenance']['post_id']==9


def test_truncated_list_body_is_replaced_by_verified_detail():
    p=post(reads=10);p['truncated']=True
    full=Mock();full.json.return_value={**p,'truncated':False,'cooked':'<p>Full email evidence beyond the preview</p>'}
    with patch.object(forums,'public_get',side_effect=[robots(),reply([p]),reply([]),full]) as get:
        rows,meta=sources.fetch('nodered','email',1,365)
    assert rows[0]['raw_text']=='Full email evidence beyond the preview'
    assert rows[0]['provenance']['body_complete_verified'] is True
    assert get.call_args.args[1]=='https://discourse.nodered.org/posts/10.json'
    assert len(meta['detail_requests'])==1


def test_wrong_detail_identity_does_not_turn_preview_into_evidence():
    p=post();p['truncated']=True
    full=Mock();full.json.return_value={**p,'id':999,'truncated':False}
    with patch.object(forums,'public_get',side_effect=[robots(),reply([p]),reply([]),full]):
        rows,meta=sources.fetch('nodered','email',1,365)
    assert rows==[] and not meta['complete'] and '身份' in meta['error']


def test_full_body_request_cap_is_explicit_not_silent_truncation():
    p=post();p['truncated']=True
    with patch.object(forums,'MAX_DETAIL_REQUESTS',0),patch.object(forums,'public_get',
            side_effect=[robots(),reply([p]),reply([])]) as get:
        rows,meta=sources.fetch('nodered','email',1,365)
    assert rows==[] and not meta['complete'] and meta['stop_reason']=='detail_limit'
    assert get.call_count==3
