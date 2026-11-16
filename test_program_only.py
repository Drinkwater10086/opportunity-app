"""Current public app behavior, independent of archived provider fixtures."""
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app
from test_app import login
from test_local_analysis import seed


def test_external_generation_routes_are_absent_and_cannot_make_requests(tmp_path):
    with patch.object(app,'DATA',tmp_path),TestClient(app.app) as client:
        login(client)
        with patch('requests.sessions.Session.request',side_effect=AssertionError('no provider network allowed')):
            for path in ['/api/config','/api/ai-unlock','/api/batches/B1/analyze','/api/batches/B1/stability-run']:
                assert client.post(path,json={}).status_code==404
            assert client.get('/api/config').status_code==404
            assert client.get('/api/batches/B1/stability-run').status_code==404
        schema=client.get('/openapi.json').json()['paths']
        assert not set(schema)&app._RETIRED_MODEL_PATHS


def test_web_collects_and_links_to_program_without_model_settings():
    root=Path(__file__).parent
    html=(root/'index.html').read_text(encoding='utf8')
    js=(root/'ui.js').read_text(encoding='utf8')
    for removed in ['key-form','analysis-form','analysis-panel','verification-provider','运行两次独立聚类','DeepSeek','智谱']:
        assert removed not in html+js
    assert 'batch-form' in html and 'user-form' in html
    assert '/collection-evidence.json' in js and '/local?batch=' in js


def test_collection_evidence_does_not_export_historical_model_calls(tmp_path):
    with patch.object(app,'DATA',tmp_path),TestClient(app.app) as client:
        login(client);seed('B1')
        response=client.get('/api/batches/B1/collection-evidence.json')
        assert response.status_code==200
        data=response.json()
        assert set(data)=={'batch','records','sources'}
        assert data['records'] and data['batch']['id']=='B1'
        assert client.get('/api/batches/missing/collection-evidence.json').status_code==404
