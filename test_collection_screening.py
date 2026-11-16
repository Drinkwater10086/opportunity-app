"""Synthetic role contrasts and end-to-end collection evidence retention."""
import csv
import io
from unittest.mock import patch

import pytest
import collection_screening as roles
import local_analysis
from local_routes import LocalConfig
from test_pipeline import client, source_fixture


@pytest.mark.parametrize('title,body,kind,role', [
    ('Ask HN: Who is hiring? (November 2026)',
     "We're looking for engineers who enjoy workflow automation, OCR, LLMs in production. Compensation: $150k plus equity.", 'comment', 'job_posting'),
    ('Ask HN: Who wants to be hired? (October 2026)',
     'Multimodal AI for document understanding. I can work on an existing model or take a problem to a production API.', 'comment', 'job_seeking'),
    ('Open positions', 'We are hiring engineers. Apply now. Our team needs AI meeting transcription using a Whisper model API.', 'story', 'job_posting'),
    ('Developer profile', 'I am looking for a job. Experience: OCR data extraction using an AI model API.', 'comment', 'job_seeking'),
    ('[dead]', 'Friendly Link Exchange Request: Our AI meeting assistant. Tool name: NoteTool. Category: AI Productivity.', 'story', 'product_promotion'),
    ('Show HN: Document tool', 'Our platform can extract PDF data and automate workflows. Give it a try.', 'story', 'product_promotion'),
    ('Invoice OCR API', 'We built an AI tool. Key features: The API converts invoices into data. Our team needs AI invoice extraction with an OCR model API.', 'story', 'product_promotion'),
    ('求职：算法工程师', '我需要一份算法开发岗位，熟悉AI图像识别模型和API。', 'topic', 'job_seeking'),
    ('招聘开发人员', '招聘岗位：工程师。岗位职责：开发AI文本分类模型。薪资待遇：面议。', 'topic', 'job_posting'),
    ('产品发布', '我们发布了会议转写工具，产品功能包含AI语音识别，立即注册免费试用。', 'topic', 'product_promotion'),
    ('Launch HN: A builder', 'For teams building AI workflows, sample.me can surface live discussions and generate reply drafts. This helps sell your product.', 'comment', 'product_promotion'),
])
def test_noise_is_identified_before_opportunity_scoring(title, body, kind, role):
    text = title + '\n' + body
    report = roles.inspect(title, text, {'item_type': kind})
    assert report['role'] == role and report['exclude']
    assert report['signals']
    for signal in report['signals']:
        source = title if signal['origin'] == 'title' else text
        assert source[signal['start']:signal['end']] == signal['text']
    record = {'id': 'S1', 'title': title, 'content': text, 'source': 'Hacker News',
              'metadata': {'provenance': {'item_type': kind}}}
    for method in ('evidence_strength', 'completeness'):
        config = LocalConfig(threshold=0, score_method=method).model_dump()
        judgment = local_analysis.judge(record, '人工智能', config)
        assert judgment['opportunity'] == 0 and judgment['excluded']
        assert 'collection_noise' in judgment['hard_gate_failures']
        assert judgment['function'] == judgment['industry'] == ''


@pytest.mark.parametrize('title,body,kind', [
    ('Ask HN: Who is hiring?', 'Our team cannot screen all applications. We need AI to classify resumes using an NLP model API.', 'comment'),
    ('Ask HN: Who wants to be hired?', 'Our team cannot extract resume fields. How can we extract them using an OCR AI model API?', 'comment'),
    ('Show HN: A meeting app', 'Our team needs AI meeting transcription using a Whisper model API.', 'comment'),
    ('Show HN: A meeting app', 'I built a tool. Our team cannot transcribe noisy meetings. How can we improve our Whisper API? We need meeting transcription.', 'comment'),
    ('How can I build recruitment automation?', 'Our team needs AI to classify resumes using an NLP model API. Manual screening takes time.', 'topic'),
    ('招聘简历筛选工具求助', '我们无法逐份处理简历，希望有工具。我们需要AI自动化筛选简历，如何用NLP模型实现？', 'topic'),
    ('Which invoice tool should we use?', 'Our team needs AI invoice extraction using an OCR model API.', 'story'),
    ('Question', '> We are hiring engineers. Apply now.\n\nOur team needs AI meeting transcription using a Whisper model API.', 'comment'),
    ('Tool question', 'sample.me can extract invoice fields. Our team cannot handle missing fields. How can we improve extraction using an OCR model API?', 'comment'),
])
def test_actual_business_requests_and_quoted_history_are_not_quarantined(title, body, kind):
    report = roles.inspect(title, title + '\n' + body, {'item_type': kind})
    assert not report['exclude'], report


def test_long_record_is_fully_checked_without_mutating_original():
    body = 'Background context. ' * 4000 + '\nFriendly Link Exchange Request for our AI meeting tool.'
    before = body
    report = roles.inspect('tool', body)
    assert report['exclude'] and body == before
    assert any(s['start'] > 16000 for s in report['signals'] if s['origin'] == 'content')


def test_collection_flags_noise_keeps_result1_and_forces_result2_zero(client):
    base = source_fixture('hackernews', 'test', 10, 365)[0][0]
    rows = [
        {**base, 'title': 'Ask HN: Who is hiring?', 'raw_text': "We're looking for engineers. Salary and equity. Our team needs AI meeting transcription with a Whisper API.",
         'url': 'https://news.ycombinator.com/item?id=1', 'provenance': {'item_type': 'comment'}},
        {**base, 'title': 'Friendly link exchange', 'raw_text': 'Friendly Link Exchange Request. Our team needs AI meeting transcription with a Whisper model API.',
         'url': 'https://news.ycombinator.com/item?id=2', 'provenance': {'item_type': 'story'}},
        {**base, 'title': 'Meeting transcription question', 'raw_text': 'Our team needs AI meeting transcription using a Whisper model API.',
         'url': 'https://news.ycombinator.com/item?id=3', 'provenance': {'item_type': 'comment'}},
    ]
    with patch('app.sources.fetch', return_value=(rows + [rows[0]], {'complete': True})):
        response = client.post('/api/batches', json={'direction': '人工智能', 'query': 'meeting', 'sources': ['hackernews']})
    bid = response.json()['id'];batch = client.get('/api/batches/' + bid).json()
    assert batch['batch']['status'] == 'collected'
    assert [r['id'] for r in batch['records']] == ['S00001', 'S00002', 'S00003']
    assert [r['metadata']['collection_screening']['exclude'] for r in batch['records']] == [True, True, False]
    import json
    log = json.loads(batch['sources'][0]['metadata'])
    assert log['deduplicated_count'] == 1 and log['content_screening']['examined_count'] == 3
    assert log['content_screening']['quarantined_count'] == 2
    rid = client.post(f'/api/batches/{bid}/local-runs', json={}).json()['id']
    base_url = f'/api/batches/{bid}/local-runs/{rid}'
    saved = client.get(base_url).json()['result']
    assert saved['record_count'] == 3 and saved['candidate_count'] == 1
    assert [saved['judgments'][r]['opportunity'] for r in ('S00001', 'S00002', 'S00003')] == [0, 0, 1]
    assert saved['clusters'][0]['records'] == ['S00003']
    tables = {}
    for number in range(1, 5):
        response = client.get(base_url + f'/result{number}.csv')
        tables[number] = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(tables[1]) == len(tables[2]) == 4
    assert len(tables[3]) == len(tables[4]) == 2
    assert tables[2][1][2] == tables[2][2][2] == '0'
    assert client.get(base_url + '/submission-check.json').json()['passed']
    assert client.get('/api/batches/' + bid).json() == batch
