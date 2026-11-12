"""Synthetic API responses; no fixture data enters the real database."""
from unittest.mock import Mock, patch
from datetime import datetime,timezone,timedelta
import pytest
import sources
import app
from test_pipeline import client


def response(data, status=200):
    r = Mock(status_code=status, headers={})
    r.json.return_value = data
    return r


def test_hn_comment_provenance_and_zero_based_pagination():
    payload = {'hits': [{'objectID': '123', '_tags': ['comment'], 'story_id': 100,
                        'story_title': 'Office &amp; automation',
                        'comment_text': '<p>Need help contact me@example.com</p>',
                        'created_at': '2026-11-01T00:00:00Z'}], 'nbPages': 3, 'nbHits': 201}
    with patch.object(sources, '_cooldown', {}), patch.object(sources.requests, 'get', return_value=response(payload)) as get:
        rows, meta = sources.fetch_page('hackernews', 'office', 100, 365, 2)
    params = get.call_args.kwargs['params']
    assert params['page'] == 1 and params['hitsPerPage'] == 100
    assert 'created_at_i>=' in params['numericFilters'] and 'created_at_i<=' in params['numericFilters']
    assert rows[0]['url'] == 'https://news.ycombinator.com/item?id=123'
    assert rows[0]['title'] == 'Office & automation'
    assert '<p>' not in rows[0]['raw_text'] and 'me@example.com' not in rows[0]['raw_text']
    assert rows[0]['provenance']['parent_story_id'] == 100
    assert meta['has_more'] is True


def test_hn_empty_story_does_not_fabricate_article_body():
    payload = {'hits': [{'objectID': '3', '_tags': ['story'], 'title': 'Article', 'created_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
                        'url': 'https://external.example/article'}], 'nbPages': 1, 'nbHits': 1}
    with patch.object(sources, '_cooldown', {}), patch.object(sources.requests, 'get', return_value=response(payload)) as get:
        rows, meta = sources.fetch_page('hackernews', 'article', 10, 365)
    assert rows[0]['raw_text'] == '' and not rows[0]['provenance']['body_available']
    assert '仅标题' in rows[0]['provenance']['body_method']
    assert not meta['has_more'] and get.call_count == 1


@pytest.mark.parametrize('site', ['superuser', 'workplace'])
def test_stack_sites_use_correct_site_and_shared_backoff(site):
    payload = {'items': [{'title': 'Question', 'body': '<p>Workflow problem</p>',
                         'link': 'https://superuser.com/questions/123', 'content_license': 'CC BY-SA 4.0', 'creation_date':int((datetime.now(timezone.utc)-timedelta(days=1)).timestamp())}],
               'has_more': False, 'backoff': 120}
    with patch.object(sources, '_cooldown', {}), patch.object(sources.requests, 'get', return_value=response(payload)) as get:
        rows, _ = sources.fetch_page(site, 'workflow', 10, 365)
        assert get.call_args.kwargs['params']['site'] == site
        assert rows[0]['raw_text'] == 'Workflow problem'
        with pytest.raises(ValueError, match='冷却'):
            sources.fetch('stackoverflow', 'workflow', 10, 365)
        assert get.call_count == 1


@pytest.mark.parametrize('license_value', [None, '', 42])
def test_missing_or_invalid_stack_license_is_not_fabricated(license_value):
    payload={'items':[{'title':'Example','body':'Evidence',
                       'link':'https://superuser.com/questions/123',
                       'content_license':license_value,'creation_date':int((datetime.now(timezone.utc)-timedelta(days=1)).timestamp())}], 'has_more':False}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        rows,_=sources.fetch_page('superuser','workflow',10,365)
    assert '未提供' in rows[0]['license'] and '4.0' not in rows[0]['license']


def test_unknown_source_rejected_before_network():
    with patch.object(sources.requests, 'get') as get:
        with pytest.raises(ValueError):
            sources.fetch_page('arbitrary', 'query', 10, 365)
        get.assert_not_called()


def test_long_backoff_between_pages_preserves_first_page_without_sleep():
    payload = {'items': [{'title': 'Question', 'body': 'Evidence',
                         'link': 'https://superuser.com/questions/123','creation_date':int((datetime.now(timezone.utc)-timedelta(days=1)).timestamp())}],
               'has_more': True, 'backoff': 120}
    with patch.object(sources, '_cooldown', {}), patch.object(sources.requests, 'get', return_value=response(payload)) as get, \
            patch.object(sources.time, 'sleep', side_effect=AssertionError('must not block on long backoff')):
        rows, meta = sources.fetch('superuser', 'workflow', 200, 365)
    assert len(rows) == 1 and not meta['complete'] and '冷却' in meta['error']
    assert get.call_count == 1


def test_exhausted_quota_stops_before_next_query_even_when_last_page():
    with patch.object(sources, '_cooldown', {}), patch.object(sources, 'fetch_page',
            return_value=([{'url': 'https://example.test/1'}], {'has_more': False, 'quota_remaining': 0})) as fetch:
        rows, meta = sources.fetch('superuser', 'first\nsecond', 100, 365)
    assert len(rows) == 1 and not meta['complete']
    assert fetch.call_count == 1 and '配额' in meta['error']


def test_zero_quota_after_all_requested_data_is_success():
    with patch.object(sources, '_cooldown', {}), patch.object(sources, 'fetch_page',
            return_value=([{'url': 'https://example.test/1'}], {'has_more': True, 'quota_remaining': 0})):
        rows, meta = sources.fetch('superuser', 'first', 1, 365)
    assert len(rows) == 1 and meta['complete']


def test_new_source_collection_preserves_provenance(client):
    def fetch(source, *args, **kwargs):
        return [dict(title=source, raw_text='Synthetic workflow evidence',
                     url=f'https://news.ycombinator.com/item?id={source}', published_at=None,
                     updated_at=None, stars=None, heat={}, license='synthetic',
                     provenance={'item_type': 'comment'})], {'complete': True}
    with patch.object(app.sources, 'fetch', side_effect=fetch):
        r = client.post('/api/batches', json={'direction': '办公自动化', 'query': 'workflow',
                                             'sources': ['hackernews', 'superuser', 'workplace']})
    assert r.status_code == 202
    data = client.get('/api/batches/' + r.json()['id']).json()
    assert data['batch']['status'] == 'collected' and len(data['records']) == 3
    assert all(x['metadata']['provenance']['item_type'] == 'comment' for x in data['records'])
    assert {x['source'] for x in data['records']} == {'Hacker News', 'Super User', 'The Workplace'}
