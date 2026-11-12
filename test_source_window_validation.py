"""Provider results must match the batch's requested time window."""
from datetime import datetime,timezone
from unittest.mock import Mock,patch
import pytest
import sources

END=datetime(2025,2,1,tzinfo=timezone.utc)


def response(payload):
    r=Mock(status_code=200,headers={});r.json.return_value=payload;return r


@pytest.mark.parametrize('source,good,bad,payload_meta',[
    ('github_issues',
     {'title':'good','html_url':'https://github.com/x/y/issues/1','created_at':'2025-01-25T00:00:00Z'},
     {'title':'old','html_url':'https://github.com/x/y/issues/2','created_at':'2024-01-01T00:00:00Z'},
     {'total_count':2}),
    ('stackoverflow',
     {'title':'good','link':'https://stackoverflow.com/questions/1','creation_date':1737763200},
     {'title':'old','link':'https://stackoverflow.com/questions/2','creation_date':1704067200},
     {'has_more':False}),
    ('hackernews',
     {'objectID':'1','title':'good','created_at':'2025-01-25T00:00:00Z','_tags':['story']},
     {'objectID':'2','title':'old','created_at':'2024-01-01T00:00:00Z','_tags':['story']},
     {'nbPages':1,'nbHits':2}),
])
def test_outside_window_is_removed_and_source_is_not_marked_complete(source,good,bad,payload_meta):
    payload={('hits' if source=='hackernews' else 'items'):[good,bad],**payload_meta}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response(payload)):
        rows,meta=sources.fetch(source,'workflow',10,30,window_end=END)
    assert [r['title'] for r in rows]==['good']
    assert not meta['complete'] and meta['pages'][0]['outside_window_count']==1


def test_repository_may_be_old_when_recently_updated():
    item={'name':'old repo','html_url':'https://github.com/x/y',
          'created_at':'2020-01-01T00:00:00Z','pushed_at':'2025-01-25T00:00:00Z'}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response({'items':[item],'total_count':1})):
        rows,meta=sources.fetch('github','workflow',10,30,window_end=END)
    assert len(rows)==1 and meta['complete']


def test_missing_publication_time_is_not_accepted_as_valid_record():
    item={'title':'no date','link':'https://stackoverflow.com/questions/1'}
    with patch.object(sources,'_cooldown',{}),patch.object(sources.requests,'get',return_value=response({'items':[item],'has_more':False})):
        rows,meta=sources.fetch('stackoverflow','workflow',10,30,window_end=END)
    assert not rows and not meta['complete']
    assert meta['pages'][0]['invalid_date_count']==1
