"""Isolated collection and program-analysis integration fixtures."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
import app
from test_app import login


def source_fixture(source, query, limit, days, window_end=None):
    text = '教师需要使用AI批改作业并生成个性化反馈' if source == 'github' else '老师希望AI帮助批改作业，减少重复劳动'
    return [dict(title=source+' synthetic', raw_text=text, url=('https://github.com/example/test' if source == 'github' else 'https://stackoverflow.com/questions/123/test'),
                 published_at='2026-01-01', updated_at='2026-11-01', stars=5 if source == 'github' else None,
                 heat={'测试热度': 5}, license='合成测试数据')], {'returned_count': 1}


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmp, patch.object(app,'DATA',Path(tmp)), patch.object(app.sources,'fetch',side_effect=source_fixture):
        with TestClient(app.app) as c:
            login(c)
            yield c


def collect(c):
    response=c.post('/api/batches',json={'direction':'教育','query':'test','sources':['github','stackoverflow']})
    assert response.status_code==202
    return response.json()['id']


def test_collection_to_program_analysis_exports_and_permissions(client):
    bid=collect(client)
    assert len(client.get(f'/api/batches/{bid}').json()['records'])==2
    response=client.post(f'/api/batches/{bid}/local-runs',json={})
    assert response.status_code==202
    run=response.json()['id'];base=f'/api/batches/{bid}/local-runs/{run}'
    assert client.get(base).json()['status']=='complete'
    for n in range(1,5):assert client.get(base+f'/result{n}.csv').status_code==200
    assert client.get(base+'/evidence.json').status_code==200
    assert client.post('/api/users',json={'username':'decider','password':'another-test-password','role':'decision'}).status_code==200
    client.post('/api/logout',json={})
    assert client.get(base).status_code==401
    client.post('/api/login',json={'username':'decider','password':'another-test-password'})
    assert client.get(base+'/result4.csv').status_code==200
    assert client.post('/api/batches',json={'direction':'教育','query':'test'}).status_code==403
    assert client.post(f'/api/batches/{bid}/local-runs',json={}).status_code==403


def test_partial_collection_preserves_data_and_prevents_incomplete_analysis(client):
    def partial(source,*args,**kwargs):
        if source=='stackoverflow':raise ValueError('source unavailable')
        return source_fixture(source,*args,**kwargs)
    with patch.object(app.sources,'fetch',side_effect=partial):bid=collect(client)
    data=client.get(f'/api/batches/{bid}').json()
    assert data['batch']['status']=='partial' and len(data['records'])==1
    assert len(data['sources'])==2
    assert client.get(f'/api/batches/{bid}/result1.csv').status_code==200
    assert client.post(f'/api/batches/{bid}/local-runs',json={}).status_code==409


def test_clone_preserves_collection_and_creates_separate_analysis_history(client):
    bid=collect(client)
    original=client.get(f'/api/batches/{bid}').json()
    new=client.post(f'/api/batches/{bid}/clone',json={}).json()['id']
    assert new!=bid
    assert [{k:v for k,v in r.items() if k!='batch_id'} for r in client.get(f'/api/batches/{new}').json()['records']]==[{k:v for k,v in r.items() if k!='batch_id'} for r in original['records']]
    assert client.get(f'/api/batches/{new}/local-runs').json()==[]
    assert client.get(f'/api/batches/{bid}').json()==original
