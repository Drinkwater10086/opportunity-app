"""Program-only application routes and release surface."""
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
        assert not set(schema)&{'/api/config','/api/ai-unlock','/api/batches/{batch_id}/analyze','/api/batches/{batch_id}/stability-run'}


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
        with app.connect() as db:
            db.execute('CREATE TABLE model_calls(id INTEGER PRIMARY KEY,payload TEXT)')
            db.execute("INSERT INTO model_calls VALUES (1,'historical audit marker')")
        response=client.get('/api/batches/B1/collection-evidence.json')
        assert response.status_code==200
        data=response.json()
        assert set(data)=={'batch','records','sources'}
        assert data['records'] and data['batch']['id']=='B1'
        assert 'historical audit marker' not in client.get('/api/batches/B1/evidence.json').text
        with app.connect() as db:
            assert db.execute('SELECT payload FROM model_calls WHERE id=1').fetchone()[0]=='historical audit marker'
        assert client.get('/api/batches/missing/collection-evidence.json').status_code==404


def test_provider_implementation_is_not_packaged():
    import analysis_engine
    for name in ('call_model','PROVIDERS','SYSTEM','judgment_prompt'):
        assert not hasattr(analysis_engine,name)
    for name in ('request_analysis','request_provider','model_key','run_analysis'):
        assert not hasattr(app,name)


def test_release_pages_and_primary_docs_use_current_workflow():
    root=Path(__file__).parent
    for name in ('index.html','local.html','ui.js','local-ui.js','README.md','USER_GUIDE.md','docs/index.html'):
        text=(root/name).read_text(encoding='utf8')
        for obsolete in ('DeepSeek','智谱','AI分析','AI 分析','大模型分析','外部生成式','研究原型','在线测试版','实验评价'):
            assert obsolete not in text,(name,obsolete)
