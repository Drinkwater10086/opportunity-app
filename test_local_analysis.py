"""Synthetic unit inputs only; never presented as collected competition data."""
import csv
import io
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app
import local_analysis as core
from local_routes import LocalConfig, RUN_LOCK


def record(i, text=None):
    return {'id': f'S{i:05d}', 'content': text or f'Our team needs meeting transcription using a Whisper model API. Manual meeting reports take time. variant {i}',
            'title': f'Meeting transcription {i}', 'source': 'GitHub', 'url': f'https://github.com/test/{i}',
            'raw_text': text or '', 'published_at': None, 'updated_at': None, 'stars': 1,
            'collected_at': '2026-11-14T00:00:00Z'}


def test_rules_offsets_negation_and_irrelevant():
    cfg = LocalConfig().model_dump()
    positive = core.judge(record(1), '企业办公自动化', cfg)
    assert positive['opportunity'] == 1
    for span in positive['evidence_spans'].values():
        if span:
            assert record(1)['content'][span['start']:span['end']] == span['text']
    for text in ['Our team needs meeting reports without AI. We use a manual workflow API.',
                 'Our team needs email storage, using a manual workflow API.',
                 'Our team needs a Whisper model API for meeting transcription. Buy now!',
                 'Our patients need a medical OCR model API for diagnosis.']:
        assert core.judge(record(1, text), '企业办公自动化', cfg)['opportunity'] == 0


def test_full_long_text_evidence_and_rule_limits():
    text = 'We need something unrelated. ' + ('background information. '*1000) + record(1)['content']
    j = core.judge(record(1, text), '企业办公自动化', LocalConfig().model_dump())
    assert j['opportunity'] == 1
    assert j['evidence_spans']['need']['start'] > 16000
    assert core.judge(record(1, 'need AI'), '企业办公自动化', LocalConfig().model_dump())['opportunity'] == 0


def test_deterministic_clusters_coverage_and_evaluation():
    rows = [record(i) for i in range(1, 5)] + [record(5, 'Pure tutorial for beginners without any business problem.')]
    batch = {'direction': '企业办公自动化'}
    cfg = LocalConfig().model_dump()
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
        a = core.analyze(batch, rows, cfg, 2)
        b = core.analyze(batch, list(reversed(rows)), cfg, 2)
    assert a == b
    assert a['candidate_count'] == 4
    assert a['evaluation']['structure_valid']
    assert sorted(r for c in a['clusters'] for r in c['records']) == [r['id'] for r in rows[:4]]
    assert all(c['coverage_score'] == 50 for c in a['clusters'])
    assert a['evaluation']['sensitivity']
    assert a['evaluation']['baseline_labels']


def test_zero_and_single_candidate_are_explicit():
    cfg = LocalConfig().model_dump()
    zero = core.analyze({'direction':'企业办公自动化'}, [record(1, 'hello')], cfg, 1)
    assert zero['candidate_count'] == 0 and zero['clusters'] == []
    assert zero['evaluation']['primary']['silhouette'] is None
    one = core.analyze({'direction':'企业办公自动化'}, [record(1)], cfg, 1)
    assert one['evaluation']['primary']['silhouette'] is None
    assert '未执行LSA' in one['representation']
    with pytest.raises(ValueError):
        LocalConfig(coverage_weight=0, scale_weight=0)
    with pytest.raises(ValueError):
        LocalConfig(threshold=float('nan'))


def seed(bid):
    with app.connect() as db:
        db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)', (bid,'企业办公自动化','meeting',10,365,'2026-11-14','collected',''))
        db.execute('INSERT INTO batch_options VALUES (?,?)', (bid,'["github"]'))
        for i in range(1, 5):
            r = record(i)
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (bid,r['id'],r['source'],r['url'],r['title'],r['content'],r['content'],None,None,1,r['collected_at']))


def login_if_needed(client):
    if client.get('/api/session').json().get('needs_setup'):
        creds = {'username':'tester','password':'local-analysis-test'}
        assert client.post('/api/setup',json=creds).status_code == 200
        assert client.post('/api/login',json=creds).status_code == 200


def test_routes_no_key_isolation_exports_and_legacy_untouched(tmp_path):
    with patch.object(app, 'DATA', tmp_path), TestClient(app.app) as client:
        login_if_needed(client)
        seed('B1'); seed('B2')
        with app.connect() as db:
            db.execute("INSERT INTO analyses(batch_id,status,config) VALUES ('B1','complete','{}')")
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
            response = client.post('/api/batches/B1/local-runs',json={})
        assert response.status_code == 202, response.text
        rid = response.json()['id']
        base = f'/api/batches/B1/local-runs/{rid}'
        run = client.get(base).json()
        assert run['status'] == 'complete', run
        assert client.get('/api/batches/B2/local-runs/'+rid).status_code == 404
        for n in range(1, 5):
            response = client.get(base+f'/result{n}.csv')
            assert response.status_code == 200
            rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
            assert len(rows) > 1 and rows[1][0] == 'B1'
        assert client.get(base+'/proposal/C1.md').status_code == 200
        assert client.get(base+'/proposal/missing.md').status_code == 404
        assert client.get(base+'/evidence.json').json()['result']['input_sha256']
        assert client.get('/local').status_code == 200
        assert client.get('/local-ui.js').status_code == 200
        assert client.post('/api/batches/B1/local-runs',json={'scale_weight':0,'coverage_weight':0}).status_code == 422
        assert client.post('/api/batches/B1/local-runs',json={},headers={'origin':'https://evil.example'}).status_code == 403
        RUN_LOCK.acquire()
        try:
            assert client.post('/api/batches/B1/local-runs',json={}).status_code == 409
        finally:
            RUN_LOCK.release()
        with app.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0
            assert db.execute("SELECT config FROM analyses WHERE batch_id='B1'").fetchone()[0] == '{}'
            assert db.execute('SELECT COUNT(*) FROM judgments').fetchone()[0] == 0
        second = client.post('/api/batches/B1/local-runs',json={}).json()['id']
        assert second != rid
        assert len(client.get('/api/batches/B1/local-runs').json()) == 2
        with app.connect() as db:
            db.execute("UPDATE batches SET status='partial' WHERE id='B2'")
        assert client.post('/api/batches/B2/local-runs',json={}).status_code == 409
        with patch.object(app.source_policy, 'issues', return_value=[{'name':'blocked','reason':'test'}]):
            assert client.post('/api/batches/B1/local-runs',json={}).status_code == 409


def test_failed_worker_releases_lock_and_preserves_error(tmp_path):
    with patch.object(app,'DATA',tmp_path), TestClient(app.app) as client:
        login_if_needed(client); seed('B1')
        with patch.object(core,'analyze',side_effect=ValueError('intentional test failure')):
            rid = client.post('/api/batches/B1/local-runs',json={}).json()['id']
        run = client.get('/api/batches/B1/local-runs/'+rid).json()
        assert run['status']=='failed' and 'intentional' in run['error']
        assert not RUN_LOCK.locked()
