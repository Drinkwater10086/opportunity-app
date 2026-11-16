"""Synthetic fixtures only; do not store them in the application database."""
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
import app
import analysis_engine as engine
from test_app import login


def source_fixture(source, query, limit, days, window_end=None):
    text = '教师需要使用AI批改作业并生成个性化反馈' if source == 'github' else '老师希望AI帮助批改作业，减少重复劳动'
    return [dict(title=source+' synthetic', raw_text=text, url=('https://github.com/example/test' if source == 'github' else 'https://stackoverflow.com/questions/123/test'),
                 published_at='2026-01-01', updated_at='2026-11-01', stars=5 if source == 'github' else None,
                 heat={'测试热度': 5}, license='合成测试数据')], {'returned_count': 1}


def judgment(evidence):
    return dict(relevant=True, scope_relation="direct", real_need=True, ai_core=True, feasible=True, excluded=False, confidence=0.9,
                function='文本生成', industry='教育', evidence=evidence, reason='测试用判断',
                pain='重复批改作业', target_user='教师', need_kind='explicit_request',
                need_evidence=evidence, user_evidence=evidence, ai_evidence=evidence, feasibility_evidence=evidence)


def model_fixture(key, prompt, max_tokens):
    if prompt['task'] == '逐条机会判别':
        data = judgment(re.split(r'synthetic\s+', prompt['content'], maxsplit=1)[1])
    else:
        data = {'clusters': [{'name':'教师作业批改与反馈','function':'文本生成','industry':'教育',
                              'records':[r['id'] for r in prompt['opportunities']]}]}
    return {'model':'test-model-not-real', 'usage':{'prompt_tokens':100,'completion_tokens':100},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data,ensure_ascii=False)}}]}


@pytest.fixture
def client():
    # Archived mocked-provider regressions only. Production does not register
    # these routes; current public behavior is tested in test_program_only.py.
    current_routes=list(app.app.router.routes)
    app.app.router.routes.extend(app._RETIRED_MODEL_ROUTES)
    app.app.openapi_schema=None
    with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DATA', Path(tmp)), patch.object(app, 'MODEL_KEY', 'synthetic-key-not-real'), patch.object(app.sources, 'fetch', side_effect=source_fixture):
        try:
            with TestClient(app.app) as c:
                login(c)
                yield c
        finally:
            app.app.router.routes[:]=current_routes
            app.app.openapi_schema=None


def collect(c):
    response = c.post('/api/batches',json={'direction':'测试教育需求','query':'test','sources':['github','stackoverflow']})
    assert response.status_code == 202
    return response.json()['id']


def test_complete_pipeline_exports_reviews_and_permissions(client):
    bid = collect(client)
    assert len(client.get(f'/api/batches/{bid}').json()['records']) == 2
    with patch.object(engine, 'call_model', side_effect=model_fixture) as call:
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code == 202
        assert call.call_count == 3
    data = client.get(f'/api/batches/{bid}').json()
    a = data['analysis']
    assert a['status'] == 'complete', a['error']
    assert a['clusters'][0]['score'] == 100
    assert a['evaluation']['accuracy'] is None
    for n in (1,2,3,4):
        assert client.get(f'/api/batches/{bid}/result{n}.csv').status_code == 200
    proposal = client.get(f'/api/batches/{bid}/clusters/C1/proposal.md')
    assert proposal.status_code == 200
    assert 'S00001' in proposal.text and 'S00002' in proposal.text
    assert '估计' in proposal.text
    assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code == 409
    assert client.post(f'/api/batches/{bid}/reviews',json={'record_id':'S00001','label':1,'reason':'人工测试'}).status_code == 200
    assert client.post(f'/api/batches/{bid}/pair-reviews',json={'left_id':'S00001','right_id':'S00002','same_topic':1}).status_code == 200
    assert client.get(f'/api/batches/{bid}').json()['analysis']['evaluation']['pair_agreement'] == 1
    assert client.post('/api/users',json={'username':'reviewer','password':'another-test-password','role':'decision'}).status_code == 200
    client.post('/api/logout',json={})
    assert client.get(f'/api/batches/{bid}/evidence.json').status_code == 401
    client.post('/api/login',json={'username':'reviewer','password':'another-test-password'})
    assert client.get(f'/api/batches/{bid}/result4.csv').status_code == 200
    assert client.post('/api/batches',json={'direction':'测试','query':'test'}).status_code == 403
    assert client.post('/api/config',json={'api_key':'not-real-key'}).status_code == 403
    client.post(f'/api/batches/{bid}/reviews',json={'record_id':'S00001','label':0,'reason':'不同意见'})
    e=client.get(f'/api/batches/{bid}').json()['analysis']['evaluation']
    assert e['disagreements'] == 1 and e['accuracy'] is None


def test_failed_model_call_resumes_without_rejudging(client):
    bid = collect(client)
    counter = [0]
    def fail_second(key,prompt,max_tokens):
        counter[0] += 1
        if counter[0] == 2:
            raise ValueError('测试网络故障')
        return model_fixture(key,prompt,max_tokens)
    with patch.object(engine,'call_model',side_effect=fail_second):
        client.post(f'/api/batches/{bid}/analyze',json={})
    a=client.get(f'/api/batches/{bid}').json()['analysis']
    assert a['status']=='failed' and len(a['judgments'])==1
    assert len(a['calls'])==2 and a['estimated_cost_yuan']>0
    assert client.get(f'/api/batches/{bid}/result2.csv').status_code==409
    with patch.object(engine,'call_model',side_effect=model_fixture) as model:
        client.post(f'/api/batches/{bid}/analyze',json={})
        assert model.call_count==2
    assert client.get(f'/api/batches/{bid}').json()['analysis']['status']=='complete'


def test_budget_stops_before_request_and_missing_key(client):
    bid=collect(client)
    with patch.object(app,'MODEL_KEY',''),patch.dict(app.os.environ,{'DEEPSEEK_API_KEY':''}):
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==409
    with patch.object(engine,'call_model') as model:
        client.post(f'/api/batches/{bid}/analyze',json={'budget_yuan':0.00001})
        model.assert_not_called()
    assert client.get(f'/api/batches/{bid}').json()['analysis']['status']=='failed'


def test_partial_collection_preserves_success_and_blocks_analysis(client):
    def partial(source,*args,**kwargs):
        if source=='stackoverflow':
            raise ValueError('测试来源失败')
        return source_fixture(source,*args,**kwargs)
    with patch.object(app.sources,'fetch',side_effect=partial):
        bid=collect(client)
    data=client.get(f'/api/batches/{bid}').json()
    assert data['batch']['status']=='partial' and len(data['records'])==1
    assert len(data['sources'])==2
    assert client.get(f'/api/batches/{bid}/result1.csv').status_code==200
    assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==409


def test_invalid_evidence_memberships_and_zero_opportunities(client):
    with pytest.raises(ValueError):
        engine.validate_judgment(judgment('编造证据'),'真实文本',0.7)
    cluster={'name':'测试主题','function':'文本生成','industry':'教育','records':['S1','S1']}
    with pytest.raises(ValueError):
        engine.validate_clusters({'clusters':[cluster]},['S1','S2'])
    bid=collect(client)
    def negative(key,prompt,max_tokens):
        data=judgment('')
        data.update(real_need=False,confidence=0.1,function='',industry='',pain='',target_user='')
        return {'model':'test','usage':{'prompt_tokens':100,'completion_tokens':100},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}
    with patch.object(engine,'call_model',side_effect=negative) as model:
        client.post(f'/api/batches/{bid}/analyze',json={})
        assert model.call_count==2
    a=client.get(f'/api/batches/{bid}').json()['analysis']
    assert a['status']=='complete' and a['clusters']==[]
    assert len(client.get(f'/api/batches/{bid}/result4.csv').content.decode('utf-8-sig').splitlines())==1


def test_stackoverflow_adapter_cooldown_and_redaction():
    class Reply:
        status_code=200
        def raise_for_status(self): pass
        def json(self):
            return {'items':[{'title':'Test &amp; title','body':'<p>Contact a@example.com for AI</p>',
                              'link':'https://stackoverflow.com/questions/123','creation_date':int(__import__('time').time())-86400,
                              'score':2,'view_count':12,'answer_count':0}], 'backoff':120, 'has_more':False}
    with patch.object(app.sources,'_cooldown',{}),patch.object(app.sources.requests,'get',return_value=Reply()):
        rows,meta=app.sources.fetch('stackoverflow','AI',10,90)
        assert rows[0]['title']=='Test & title'
        assert 'a@example.com' not in rows[0]['raw_text']
        assert rows[0]['heat']['浏览数']==12 and meta['backoff']==120
        with pytest.raises(ValueError,match='冷却'):
            app.sources.fetch('stackoverflow','other',10,90)


def test_model_contract_and_unrelated_record():
    with patch.object(engine.requests, 'post') as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'test': 'response'}
        assert engine.call_model('fake-key', {'task':'test JSON'}, 1600) == {'test':'response'}
        kwargs = post.call_args.kwargs
        assert kwargs['json']['thinking'] == {'type':'disabled'}
        assert kwargs['json']['response_format'] == {'type':'json_object'}
        assert kwargs['json']['max_tokens'] == 1600
        assert kwargs['headers']['Authorization'] == 'Bearer fake-key'
    item = judgment('原文证据')
    item['relevant'] = False
    result = engine.validate_judgment(item, '原文证据', 0.7)
    assert result['opportunity'] == 0 and result['industry'] == ''


def test_cluster_metadata_is_ignored_but_membership_remains_strict():
    cluster={'name':'会议记录','function':'语音处理','industry':'其他','records':['S1','S2']}
    response={'clusters':[cluster], 'opportunities':[{'id':'S1'}]}
    assert engine.validate_clusters(response,['S1','S2']) == [cluster]
    with pytest.raises(ValueError):
        engine.validate_clusters(response,['S1','S2','S3'])


def test_503_records_error_separates_reserve_and_prevents_immediate_retry(client):
    bid=collect(client)
    with patch.object(engine,'call_model',side_effect=engine.ProviderError(503,60)) as model:
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==202
        a=client.get(f'/api/batches/{bid}').json()['analysis']
        assert a['status']=='failed' and '服务过载' in a['error']
        assert a['estimated_cost_yuan']==0
        assert a['unconfirmed_reserve_yuan']>0
        assert a['retry_after_seconds']>0
        assert json.loads(a['calls'][0]['usage'])['_http_status']==503
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==429
        assert model.call_count==1


def test_provider_http_error_mapping():
    with patch.object(engine.requests,'post') as post:
        post.return_value.status_code=503
        post.return_value.headers={'Retry-After':'90'}
        with pytest.raises(engine.ProviderError) as error:
            engine.call_model('fake-key',{'task':'test JSON'},1600)
        assert error.value.status_code==503 and error.value.retry_seconds==90
        assert '服务过载' in str(error.value)
    assert '余额不足' in str(engine.ProviderError(402))
    assert '身份验证失败' in str(engine.ProviderError(401))


def test_free_provider_request_contract():
    reply = type('Reply', (), {'status_code': 200, 'json': lambda self: {'ok': True}})()
    with patch.object(engine.requests, 'post', return_value=reply) as post:
        engine.call_model('synthetic-zhipu-key', {'task': 'test'}, 12000, provider='bigmodel')
    assert post.call_args.args[0] == 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    body = post.call_args.kwargs['json']
    assert body['model'] == 'glm-4-flash-250414'
    assert body['response_format'] == {'type': 'json_object'}
    assert 'thinking' not in body
    assert 'tools' not in body
    assert '智谱' in str(engine.ProviderError(503, 60, 'bigmodel'))
    assert 'DeepSeek' not in str(engine.ProviderError(503, 60, 'bigmodel'))


def test_free_pipeline_clone_and_no_mixed_models(client):
    bid = collect(client)
    with patch.object(engine, 'call_model', side_effect=model_fixture):
        assert client.post(f'/api/batches/{bid}/analyze', json={}).status_code == 202
    original = client.get(f'/api/batches/{bid}').json()
    with patch.object(app, 'MODEL_PROVIDER', 'deepseek'), patch.object(app, 'BIGMODEL_KEY', ''):
        assert client.post('/api/config', json={'provider':'bigmodel', 'api_key':'synthetic-zhipu-key'}).status_code == 200
        assert app.model_key('deepseek') == 'synthetic-key-not-real'
        assert app.model_key('bigmodel') == 'synthetic-zhipu-key'
        assert 'synthetic-zhipu-key' not in client.get('/api/config').text
        copied = client.post(f'/api/batches/{bid}/clone', json={})
        assert copied.status_code == 201
        new_id = copied.json()['id']
        data = client.get(f'/api/batches/{new_id}').json()
        assert data['analysis'] is None
        assert [r['content'] for r in data['records']] == [r['content'] for r in original['records']]
        def free_reply(key, prompt, max_tokens, provider):
            assert key == 'synthetic-zhipu-key' and provider == 'bigmodel'
            result = model_fixture(key, prompt, max_tokens)
            result['model'] = 'glm-4-flash-250414'
            return result
        with patch.object(engine, 'call_model', side_effect=free_reply):
            assert client.post(f'/api/batches/{new_id}/analyze', json={}).status_code == 202
        analysis = client.get(f'/api/batches/{new_id}').json()['analysis']
        assert analysis['status'] == 'complete', analysis['error']
        assert analysis['config']['provider'] == 'bigmodel'
        assert analysis['estimated_cost_yuan'] == 0
        assert analysis['unconfirmed_reserve_yuan'] == 0
        assert all(c['estimated_cost'] == 0 for c in analysis['calls'])
        assert client.get(f'/api/batches/{bid}').json()['analysis'] == original['analysis']
        # Failed old analyses must not resume with another provider.
        with app.connect() as db:
            db.execute("UPDATE analyses SET status='failed' WHERE batch_id=?", (bid,))
        assert client.post(f'/api/batches/{bid}/analyze', json={}).status_code == 409
        assert client.post('/api/users', json={'username':'decider','password':'synthetic-password','role':'decision'}).status_code == 200
        client.post('/api/logout', json={})
        client.post('/api/login', json={'username':'decider','password':'synthetic-password'})
        assert client.post(f'/api/batches/{bid}/clone', json={}).status_code == 403


def test_cluster_repair_feedback_preserves_exact_membership(client):
    bid = collect(client)
    bad = {'clusters':[{'name':'教师反馈','function':'文本生成','industry':'教育','records':['S00001','S00001']}]}
    reply = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(bad)}}]}
    with app.connect() as db:
        db.execute('INSERT INTO model_calls(batch_id,stage,created_at,prompt,response,usage,model,estimated_cost) VALUES (?,?,?,?,?,?,?,?)',
                   (bid,'cluster','test','{}',json.dumps(reply),'{}','test',0))
    positives = {'S00001':judgment('test'), 'S00002':judgment('test')}
    repair = app.cluster_request_prompt(bid, positives)['repair']
    assert repair['missing'] == ['S00002']
    assert repair['duplicated'] == ['S00001']
    assert repair['unknown'] == []
    assert repair['previous_invalid_output'] == bad
    with pytest.raises(ValueError):
        engine.validate_clusters(bad, positives)
