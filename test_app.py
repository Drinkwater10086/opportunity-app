import csv
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import app


def login(client):
    credentials = {'username': 'tester', 'password': 'local-test-password'}
    assert client.post('/api/setup', json=credentials).status_code == 200
    assert client.post('/api/login', json=credentials).status_code == 200


class Reply:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        item = {'name': '=Synthetic test', 'description': '同一测试简介 https://example.com',
                'html_url': 'https://github.com/example/test', 'created_at': '2026-01-01T00:00:00Z',
                'pushed_at': '2026-11-01T00:00:00Z', 'stargazers_count': 5}
        return {'items': [item, {**item, 'html_url': 'https://github.com/example/copy'}], 'total_count': 2}


def test_batch_isolation_dedup_export_and_missing_batch():
    with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DATA', Path(tmp)), patch.object(app.requests, 'get', return_value=Reply()):
        with TestClient(app.app) as client:
            login(client)
            ids = []
            for _ in range(2):
                app.sources._cooldown.clear()
                ids.append(client.post('/api/batches', json={'direction': '测试方向', 'query': 'synthetic test'}).json()['id'])
            assert ids[0] != ids[1]
            for bid in ids:
                data = client.get('/api/batches/' + bid).json()
                assert data['batch']['status'] == 'collected'
                assert len(data['records']) == 1
                assert data['records'][0]['raw_text'].endswith('https://example.com')
                assert 'https://' not in data['records'][0]['content']
                result = client.get(f'/api/batches/{bid}/result1.csv')
                rows = list(csv.reader(io.StringIO(result.content.decode('utf-8-sig'))))
                assert rows[1][0] == bid
                assert rows[1][4].startswith("'=")
            assert client.get('/api/batches/missing').status_code == 404


def test_failure_validation_and_cross_origin():
    with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DATA', Path(tmp)), patch.object(app.requests, 'get', side_effect=app.requests.Timeout()):
        with TestClient(app.app) as client:
            login(client)
            app.sources._cooldown.clear()
            body = {'direction': '测试方向', 'query': 'synthetic test'}
            assert client.post('/api/batches', json={**body, 'limit': 999}).status_code == 422
            assert client.post('/api/batches', json=body, headers={'Origin': 'https://evil.example'}).status_code == 403
            bid = client.post('/api/batches', json=body).json()['id']
            assert client.get('/api/batches/' + bid).json()['batch']['status'] == 'failed'
            assert client.get(f'/api/batches/{bid}/result1.csv').status_code == 409


def test_restart_marks_unfinished_task_failed():
    with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DATA', Path(tmp)):
        app.init_db()
        with app.connect() as db:
            db.execute("INSERT INTO batches VALUES ('Btest','测试','test',20,90,'2026','running','')")
        app.init_db()
        assert app.get_records('Btest')[0]['status'] == 'failed'
