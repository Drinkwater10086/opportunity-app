import json
from unittest.mock import patch
import pytest
import app
import analysis_engine as engine
from test_pipeline import client,collect,model_fixture,judgment
from test_chunking import reply


def review_result(approve=True):
    return {'scope_relation':'direct' if approve else 'outside','need_supported':True,'need_signal_type':'explicit_request','ai_supported':True,'feasibility_supported':True,'support_ids':['E0001'],'reason':'测试复核依据'}


def test_review_removes_candidate_before_clustering(client):
    b=collect(client)
    def model(key,prompt,max_tokens):
        if prompt.get('version')==engine.REVIEW_VERSION:return reply(review_result(prompt['record_id']=='S00002'))
        return model_fixture(key,prompt,max_tokens)
    with patch.object(engine,'call_model',side_effect=model):
        client.post(f'/api/batches/{b}/analyze',json={'verification_provider':'deepseek'})
    a=app.analysis_state(b)
    assert a['status']=='complete',a['error']
    assert a['judgments']['S00001']['opportunity']==0
    assert a['judgments']['S00002']['verification']['approved']
    assert a['metrics']['opportunity_count']==1
    assert a['clusters'][0]['records']==['S00002']
    assert a['config']['verification_version']==engine.REVIEW_VERSION


def test_review_rule_upgrade_cannot_silently_mix_resumed_experiment(client):
    bid=collect(client)
    with patch.object(engine,'call_model',side_effect=ValueError('synthetic interruption')):
        assert client.post(f'/api/batches/{bid}/analyze',json={'verification_provider':'deepseek'}).status_code==202
    old=app.analysis_state(bid)
    assert old['status']=='failed'
    with patch.object(engine,'REVIEW_VERSION','test-new-review-version'),patch.object(engine,'call_model') as call:
        r=client.post(f'/api/batches/{bid}/analyze',json={'verification_provider':'deepseek'})
        assert r.status_code==409 and '复核规则版本' in r.json()['detail']
        call.assert_not_called()


def test_review_never_receives_generated_rationale():
    initial=judgment('原文');initial['reason']='不应该传入的初筛推理';initial['pain']='编造痛点'
    p=engine.review_prompt({'id':'S1','source':'test','content':'原文'},'办公',initial)
    assert '不应该传入' not in json.dumps(p,ensure_ascii=False)
    assert '编造痛点' not in json.dumps(p,ensure_ascii=False)
    for d in ({**review_result(),'support_ids':[]},{**review_result(),'support_ids':['E9999']}):
        with pytest.raises(ValueError):engine.validate_review(d,p,'原文')
    echoed = {**review_result(), 'evidence_passages':[{'id':'E9999','text':'伪造'}]}
    assert engine.validate_review(echoed,p,'原文')['approved']
    echoed['support_ids']=['E9999']
    with pytest.raises(ValueError):engine.validate_review(echoed,p,'原文')


def test_reference_schema_repair_is_bounded(client):
    b=collect(client)
    def model(key,prompt,max_tokens):
        if prompt.get('record_id')=='S00001':
            if 'evidence_passages' not in prompt:return reply({})
            d=judgment('')
            for f in engine.EVIDENCE_FIELDS:
                d.pop(f);d[f+'_id']='E0001'
            if 'schema_repair' not in prompt:d.pop('user_evidence_id')
            return reply(d)
        return model_fixture(key,prompt,max_tokens)
    with patch.object(engine,'call_model',side_effect=model) as call:
        client.post(f'/api/batches/{b}/analyze',json={})
    a=app.analysis_state(b)
    assert a['status']=='complete',a['error']
    assert call.call_count==5
    assert sum(c['stage'].endswith(':schema_repair_v1') for c in a['calls'])==1


def test_review_cached_response_reused(client):
    b=collect(client)
    with app.connect() as db:db.execute("INSERT INTO analyses(batch_id,status,config) VALUES (?,'running',?)",(b,json.dumps({'provider':'deepseek'})))
    r=app.get_records(b)[1][0];initial=judgment(r['content']);initial['opportunity']=1
    cfg={'verification_provider':'deepseek','budget_yuan':5}
    with patch.object(engine,'call_model',return_value=reply(review_result())) as call:
        one=app.verify_candidate(b,r,'test',initial,{'deepseek':'fake'},cfg)
        two=app.verify_candidate(b,r,'test',initial,{'deepseek':'fake'},cfg)
    assert one==two and call.call_count==1


def test_review_repair_cache_prevents_repeated_primary_call(client):
    b=collect(client)
    with app.connect() as db:db.execute("INSERT INTO analyses(batch_id,status,config) VALUES (?,'running',?)",(b,json.dumps({'provider':'deepseek'})))
    r=app.get_records(b)[1][0];initial=judgment(r['content']);initial['opportunity']=1
    cfg={'verification_provider':'deepseek','budget_yuan':5}
    def model(key,prompt,max_tokens):
        data=review_result()
        if 'repair' not in prompt:data['support_ids']='E0001'
        return reply(data)
    with patch.object(engine,'call_model',side_effect=model) as call:
        first=app.verify_candidate(b,r,'test',initial,{'deepseek':'fake'},cfg)
        second=app.verify_candidate(b,r,'test',initial,{},cfg)
    assert first==second and call.call_count==2


def test_review_system_does_not_instruct_initial_judgment_fields():
    prompt={'version':'independent-review-v1'}
    system=engine.system_prompt('deepseek',prompt)
    assert 'confidence' not in system and 'need_kind' not in system
    assert engine.system_prompt('deepseek')==engine.SYSTEM


@pytest.mark.parametrize('signal',['product_description','unclear'])
def test_product_features_do_not_prove_demand(signal):
    r={'id':'S1','source':'test','content':'原文'}
    p=engine.review_prompt(r,'办公',judgment('原文'))
    d=review_result();d['need_signal_type']=signal
    result=engine.validate_review(d,p,'原文')
    assert not result['need_supported'] and not result['approved']
