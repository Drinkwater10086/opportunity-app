"""Recovery uses only unambiguously successful sources and preserves lineage."""
import json
from unittest.mock import patch
from test_pipeline import client, source_fixture
import app


def partial_batch(client):
    def fetch(source,query,limit,days,window_end=None):
        if source=='github_issues':
            raise ValueError('synthetic source failure')
        return source_fixture(source,query,limit,days)
    with patch.object(app.sources,'fetch',side_effect=fetch):
        response=client.post('/api/batches',json={'direction':'办公自动化','query':'test',
            'sources':['github','github_issues','stackoverflow']})
    assert response.status_code==202
    return response.json()['id']


def test_recovery_excludes_ambiguous_website_and_preserves_origin(client):
    old=partial_batch(client)
    before=client.get('/api/batches/'+old).json()
    assert before['batch']['status']=='partial' and len(before['records'])==2
    response=client.post(f'/api/batches/{old}/clone-available',json={})
    assert response.status_code==201
    new=response.json()['id']
    after=client.get('/api/batches/'+new).json()
    assert after['batch']['status']=='collected' and len(after['records'])==1
    record=after['records'][0]
    assert record['id']=='S00001' and record['source']=='Stack Overflow'
    assert record['metadata']['lineage']=={'batch_id':old,'record_id':'S00002'}
    assert {run['source'] for run in after['sources']}=={'stackoverflow'}
    meta=json.loads(after['sources'][0]['metadata'])
    assert meta['recovered_from']==old and 'github' in meta['excluded_sources']
    assert len(client.get('/api/batches/'+old).json()['records'])==2
    response=client.post(f'/api/batches/{new}/local-runs',json={})
    assert response.status_code==202
    assert client.get(f"/api/batches/{new}/local-runs/{response.json()['id']}").json()['status']=='complete'


def test_recovery_refuses_if_no_unambiguously_usable_data(client):
    old=partial_batch(client)
    with app.connect() as db:
        db.execute("delete from record_meta where batch_id=? and record_id in (select id from records where batch_id=? and source='Stack Overflow')",(old,old))
        db.execute("delete from records where batch_id=? and source='Stack Overflow'",(old,))
    response=client.post(f'/api/batches/{old}/clone-available',json={})
    assert response.status_code==409


def test_decision_role_cannot_create_recovered_batch(client):
    old=partial_batch(client)
    assert client.post('/api/users',json={'username':'decision_user','password':'sample-password','role':'decision'}).status_code==200
    client.post('/api/logout',json={})
    assert client.post('/api/login',json={'username':'decision_user','password':'sample-password'}).status_code==200
    assert client.post(f'/api/batches/{old}/clone-available',json={}).status_code==403


def test_recovery_excludes_restricted_historical_source(client):
    old=partial_batch(client)
    with app.connect() as db:
        db.execute("update records set source='n8n Community' where batch_id=? and source='GitHub'",(old,))
        db.execute("update source_runs set source='n8n' where batch_id=? and source='github'",(old,))
        db.execute('update batch_options set sources=? where batch_id=?',
                   (json.dumps(['n8n','github_issues','stackoverflow']),old))
    response=client.post(f'/api/batches/{old}/clone-available',json={})
    assert response.status_code==201 and 'n8n' in response.json()['excluded_sources']
    recovered=client.get('/api/batches/'+response.json()['id']).json()
    assert [r['source'] for r in recovered['records']]==['Stack Overflow']
    assert not recovered['source_policy_issues']


def test_recovery_excludes_historical_unverified_community_body(client):
    old=partial_batch(client)
    with app.connect() as db:
        db.execute("update records set source='Node-RED Forum' where batch_id=? and source='GitHub'",(old,))
        db.execute("update source_runs set source='nodered' where batch_id=? and source='github'",(old,))
        db.execute('update batch_options set sources=? where batch_id=?',
                   (json.dumps(['nodered','github_issues','stackoverflow']),old))
    response=client.post(f'/api/batches/{old}/clone-available',json={})
    assert response.status_code==201 and 'nodered' in response.json()['excluded_sources']
    recovered=client.get('/api/batches/'+response.json()['id']).json()
    assert [r['source'] for r in recovered['records']]==['Stack Overflow']
