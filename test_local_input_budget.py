"""Full-input budget boundaries and acceptance above the former 20M limit."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app
import local_analysis as core
from test_local_analysis import login_if_needed, record, seed


def test_complete_body_above_old_limit_is_accepted_and_records_remain_bounded():
    text = 'x' * 20_000_001
    rows = [record(1, text)]
    core.validate_input_size(rows)
    assert rows[0]['content'] is text and len(rows[0]['content']) == 20_000_001
    with pytest.raises(ValueError, match='5000'):
        core.validate_input_size(rows * (core.MAX_RECORDS + 1))


def test_exact_character_limit_and_next_character_use_identical_http_and_core_validation(tmp_path):
    with patch.object(app, 'DATA', tmp_path), TestClient(app.app) as client:
        login_if_needed(client); seed('B1')
        with app.connect() as db:
            db.execute("DELETE FROM records WHERE batch_id='B1' AND id!='S00001'")
            db.execute("UPDATE records SET content='1234567890' WHERE batch_id='B1'")
        with patch.object(core, 'MAX_CHARACTERS', 10):
            result = core.analyze({'direction': '企业办公自动化'}, [record(1, '1234567890')],
                                  app.local_routes.LocalConfig().model_dump(), 1)
            assert result['record_count'] == 1
            accepted = client.post('/api/batches/B1/local-runs', json={})
            assert accepted.status_code == 202
            run = client.get('/api/batches/B1/local-runs/' + accepted.json()['id']).json()
            assert run['status'] == 'complete' and run['result']['input_records'][0]['content'] == '1234567890'
            with app.connect() as db:
                db.execute("UPDATE records SET content='12345678901' WHERE batch_id='B1'")
            with pytest.raises(ValueError) as error:
                core.analyze({'direction': '企业办公自动化'}, [record(1, '12345678901')],
                             app.local_routes.LocalConfig().model_dump(), 1)
            rejected = client.post('/api/batches/B1/local-runs', json={})
            assert rejected.status_code == 413
            assert rejected.json()['detail'] == str(error.value)
            assert len(client.get('/api/batches/B1/local-runs').json()) == 1


def test_http_dispatch_passes_all_twenty_million_characters_unchanged(tmp_path):
    with patch.object(app, 'DATA', tmp_path), TestClient(app.app) as client:
        login_if_needed(client); seed('B1')
        text = 'x' * 20_000_000 + ' final source evidence'
        with app.connect() as db:
            db.execute("DELETE FROM records WHERE batch_id='B1' AND id!='S00001'")
            db.execute("UPDATE records SET content=? WHERE batch_id='B1'", (text,))
        # The full 1494-record real-data run separately covers the actual analysis.
        # Here assert the HTTP boundary dispatches unaltered text, avoiding another huge analysis.
        with patch.object(core, 'analyze', side_effect=ValueError('dispatch inspected')) as analyze:
            response = client.post('/api/batches/B1/local-runs', json={})
            assert response.status_code == 202
            passed = analyze.call_args.args[1]
            assert len(passed) == 1 and passed[0]['content'] == text
        with app.connect() as db:
            assert db.execute("SELECT content FROM records WHERE batch_id='B1'").fetchone()[0] == text
