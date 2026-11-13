import json
from unittest.mock import patch

import analysis_engine as engine
import app
from test_pipeline import client, collect, model_fixture
from test_chunking import reply


def completed_batch(client):
    bid = collect(client)
    with patch.object(engine, 'call_model', side_effect=model_fixture):
        assert client.post(f'/api/batches/{bid}/analyze', json={}).status_code == 202
    assert app.analysis_state(bid)['status'] == 'complete'
    return bid


def test_independent_runs_produce_ari_without_changing_final_clusters(client):
    bid = completed_batch(client)
    before = app.analysis_state(bid)['clusters']
    with patch.object(engine, 'call_model', side_effect=model_fixture) as calls:
        response = client.post(f'/api/batches/{bid}/stability-run', json={'provider': 'deepseek'})
    assert response.status_code == 202 and calls.call_count == 2
    assert client.get(f'/api/batches/{bid}/stability-run').json()['status'] == 'complete'
    report = client.get(f'/api/batches/{bid}/automatic-evaluation.json').json()
    assert report['stability']['score'] == 1.0
    assert report['stability']['valid_runs'] >= 2
    assert app.analysis_state(bid)['clusters'] == before


def test_invalid_partitions_do_not_become_valid_runs(client):
    bid = completed_batch(client)
    invalid = {'clusters': [{'name': '测试主题', 'function': '文本生成', 'industry': '教育',
                             'records': ['S00001', 'S00001']}]}
    with patch.object(engine, 'call_model', return_value=reply(invalid)) as calls:
        assert client.post(f'/api/batches/{bid}/stability-run', json={'provider': 'deepseek'}).status_code == 202
    job = client.get(f'/api/batches/{bid}/stability-run').json()
    assert calls.call_count == 4 and job['status'] == 'failed' and job['valid_runs'] == 0
    assert client.get(f'/api/batches/{bid}/automatic-evaluation.json').json()['stability']['score'] is None


def test_stability_respects_original_budget_before_call(client):
    bid = completed_batch(client)
    with app.connect() as db:
        cfg = json.loads(db.execute('select config from analyses where batch_id=?', (bid,)).fetchone()[0])
        cfg['budget_yuan'] = 0.000001
        db.execute('update analyses set config=? where batch_id=?', (json.dumps(cfg), bid))
    with patch.object(engine, 'call_model') as calls:
        assert client.post(f'/api/batches/{bid}/stability-run', json={'provider': 'deepseek'}).status_code == 202
    calls.assert_not_called()
    job = client.get(f'/api/batches/{bid}/stability-run').json()
    assert job['status'] == 'failed' and '预算' in job['error']
