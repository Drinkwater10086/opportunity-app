from unittest.mock import patch

import analysis_engine as engine
import app
from test_pipeline import client, collect, judgment


def test_other_direction_does_not_inherit_office_rules():
    record = {'id': 'S1', 'source': 'test', 'content': '教师希望使用AI识别学生作业问题。'}
    initial = judgment(record['content'])
    prompt = engine.judgment_prompt(record, '教育中的作业反馈')
    review = engine.review_prompt(record, '教育中的作业反馈', initial)
    assert prompt['research_direction'] == review['research_direction'] == '教育中的作业反馈'
    assert '办公' not in prompt['scope_rules']
    assert '办公' not in review['scope_rules'] + review['instruction']
    assert '所选方向' in prompt['scope_rules']
    assert '所选研究方向' in review['instruction']


def test_office_examples_remain_conditional():
    record = {'id': 'S1', 'source': 'test', 'content': '会议纪要'}
    office = engine.judgment_prompt(record, '企业办公自动化')
    other = engine.judgment_prompt(record, '体育赛事问答')
    assert '会议、文档、邮件' in office['scope_rules']
    assert '会议、文档、邮件' not in other['scope_rules']
    assert office['schema'] == other['schema']


def test_changed_prompt_version_cannot_mix_resume(client):
    bid = collect(client)
    with patch.object(engine, 'call_model', side_effect=ValueError('synthetic interruption')):
        assert client.post(f'/api/batches/{bid}/analyze', json={}).status_code == 202
    assert app.analysis_state(bid)['status'] == 'failed'
    with patch.object(engine, 'PROMPT_VERSION', 'test-new-prompt-version'), patch.object(engine, 'call_model') as call:
        response = client.post(f'/api/batches/{bid}/analyze', json={})
        assert response.status_code == 409
        call.assert_not_called()
