import json
from unittest.mock import patch
import pytest
import sources
import forum_sources
import app
import analysis_engine as engine
from test_pipeline import client, collect, model_fixture


@pytest.mark.parametrize('source',['n8n','make'])
def test_restricted_source_never_contacts_network(source):
    with patch.object(sources.requests,'get') as get:
        for call in (lambda:sources.fetch(source,'email',1,365),
                     lambda:forum_sources.fetch_forum(source,'email',1,365),
                     lambda:forum_sources.public_get(source,'https://example.invalid')):
            with pytest.raises(ValueError,match='已停用'):
                call()
        get.assert_not_called()


@pytest.mark.parametrize('source',['n8n','make'])
def test_restricted_source_cannot_create_batch(client,source):
    with patch.object(app.sources,'fetch') as fetch:
        response=client.post('/api/batches',json={'direction':'办公自动化','query':'email','sources':[source]})
        assert response.status_code==422 and '已停用' in response.json()['detail']
        fetch.assert_not_called()


def test_historical_restricted_batch_remains_auditable_but_not_reusable(client):
    bid=collect(client)
    with app.connect() as db:
        db.execute('UPDATE batch_options SET sources=? WHERE batch_id=?',(json.dumps(['n8n']),bid))
    data=client.get('/api/batches/'+bid).json()
    assert data['source_policy_issues'][0]['source']=='n8n'
    assert len(data['records'])==2
    for path in ('analyze','clone'):
        assert client.post(f'/api/batches/{bid}/{path}',json={}).status_code==409
    assert client.get(f'/api/batches/{bid}/result1.csv').status_code==409
    audit=client.get(f'/api/batches/{bid}/evidence.json')
    assert audit.status_code==200 and audit.json()['source_policy_issues']


def test_source_restriction_detected_from_records_even_without_options(client):
    bid=collect(client)
    with app.connect() as db:
        db.execute('DELETE FROM batch_options WHERE batch_id=?',(bid,))
        db.execute("UPDATE records SET source='Make Community' WHERE batch_id=?",(bid,))
    assert app.batch_source_issues(bid)[0]['source']=='make'


def test_restricted_historical_analysis_cannot_export_evaluation(client):
    bid=collect(client)
    with patch.object(engine,'call_model',side_effect=model_fixture):
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==202
    with app.connect() as db:
        db.execute('update batch_options set sources=? where batch_id=?',(json.dumps(['n8n']),bid))
    assert client.get(f'/api/batches/{bid}/automatic-evaluation.json').status_code==409
    assert client.get(f'/api/batches/{bid}/result2.csv').status_code==409
    assert client.get(f'/api/batches/{bid}/evidence.json').status_code==200
