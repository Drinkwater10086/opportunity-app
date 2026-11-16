"""Intent contrasts use synthetic text, never fabricated collection records."""
import numpy as np
import pytest
import local_analysis as core
from local_routes import LocalConfig


def judge(text):
    return core.judge({'id': 'S1', 'title': 'Discussion', 'content': text, 'source': 'test'},
                      '人工智能', LocalConfig(threshold=0).model_dump())


@pytest.mark.parametrize('text,reason', [
    ('Our team has meeting transcription using an AI model API. How can we turn off AI notetakers?', 'declined_ai'),
    ('我们需要关闭AI会议录制，不希望继续转写。', 'declined_ai'),
    ('Teams provide AI meeting transcription for teams using an API. They need meeting reports. Teams has had these features for years.', 'resolved_application'),
    ('I use a Whisper AI model API for our team meetings. My routine describes how to summarize meeting reports.', 'resolved_application'),
    ('We automate transcription using a Whisper model API for customers. This manual labor is gone now.', 'resolved_application'),
    ('Users face prompt injections and data extraction. Even if AI cannot upload emails using the model API, some data can leak.', 'risk_without_application_request'),
    ('What this might look like is AI assisted data extraction using a model API. Users cannot move their workflow to another platform.', 'speculative_application'),
    ('How can we prevent duplicate records in our CRM workflow using an AI model API? Concurrent executions still cause duplicates despite idempotency.', 'engineering_consistency'),
])
def test_non_application_intents_cannot_be_restored_by_lowering_score_threshold(text, reason):
    result = judge(text)
    assert not result['opportunity'] and reason in result['hard_gate_failures']
    assert result['function'] == result['industry'] == ''
    for entry in ('need_intent', 'record_intent'):
        item = result[entry]
        for span in [item['goal'], item['request'], item['unresolved'], *item['signals'].values()]:
            if span:assert text[span['start']:span['end']] == span['text']


@pytest.mark.parametrize('text', [
    'Our team currently uses a Whisper model API. We need AI meeting transcription because our team cannot handle noisy meetings.',
    'How can our team detect prompt injections using an AI classifier model API for customer emails?',
    'We want to turn off AI notetakers. Our team needs local AI meeting transcription using a Whisper model API.',
    'Our team needs AI to extract customer data from emails using a model API. We need entity resolution with fuzzy matching, not only duplicate records and idempotency.',
    'Our team needs meeting transcription using a Whisper AI model API.',
])
def test_unresolved_application_requests_survive_background_mentions(text):
    result = judge(text)
    assert result['opportunity'], result['reason']


def test_late_unresolved_task_is_preferred_to_earlier_general_benefits():
    text = ('We like our AI agents for meeting transcription using a model API. Teams need meeting summaries. '
            'I still haven\'t found a good solution for storing and querying this knowledge using an AI retrieval model API.')
    result = judge(text)
    assert result['opportunity'] and result['function'] == '知识检索'
    assert result['need_intent']['unresolved']
    assert 'querying' in result['need_intent']['goal']['text']


def test_explicit_incompatible_tasks_split_without_discarding_members():
    rows = [{'id': 'S1'}, {'id': 'S2'}]
    judgments = {'S1': {'function': '图像识别', 'need_intent': {'goal_function': '图像识别'}},
                 'S2': {'function': '知识检索', 'need_intent': {'goal_function': '知识检索'}}}
    distances = np.array([[0., .1], [.1, 0.]])
    assert len(set(core.clustered_labels(distances, .65, rows, judgments, 'flat'))) == 2
    judgments['S2']['need_intent']['goal_function'] = '图像识别'
    assert len(set(core.clustered_labels(distances, .65, rows, judgments, 'flat'))) == 1
