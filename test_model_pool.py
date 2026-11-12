import json
from unittest.mock import patch
import pytest
import app
import analysis_engine as engine
from test_pipeline import client,collect,judgment


@pytest.fixture
def pool(client):
    bid=collect(client)
    cfg={'provider':'bigmodel','fallback_enabled':True,'provider_pool':['bigmodel','deepseek']}
    with app.connect() as db:
        db.execute("INSERT INTO analyses(batch_id,status,config) VALUES (?,'running',?)",(bid,json.dumps(cfg)))
    with patch.dict(app.PROVIDER_COOLDOWNS,{},clear=True):
        yield bid


def reply(data):
    return {'usage':{'prompt_tokens':10,'completion_tokens':10},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}


def test_limit_switches_and_cooldown_skips_primary(pool):
    calls=[]
    def model(key,prompt,max_tokens,provider='deepseek'):
        calls.append(provider)
        if provider=='bigmodel':raise engine.ProviderError(429,60,provider)
        return reply({})
    with patch.object(engine,'call_model',side_effect=model):
        for stage in ('first','second'):
            assert app.request_analysis(pool,stage,{},100,{'bigmodel':'fake-b','deepseek':'fake-d'},5)=={}
    assert calls==['bigmodel','deepseek','deepseek']
    state=app.analysis_state(pool)
    assert state['estimated_cost_yuan']>0
    assert [json.loads(c['usage'])['_provider'] for c in state['calls']]==calls


def test_all_limited_stops_without_retry_loop(pool):
    def model(key,prompt,max_tokens,provider='deepseek'):
        raise engine.ProviderError(429,60,provider)
    with patch.object(engine,'call_model',side_effect=model) as call:
        with pytest.raises(engine.ProviderError):app.request_analysis(pool,'one',{},100,{'bigmodel':'fake','deepseek':'fake'},5)
        with pytest.raises(ValueError,match='模型池'):app.request_analysis(pool,'two',{},100,{'bigmodel':'fake','deepseek':'fake'},5)
        assert call.call_count==2


def test_auth_error_does_not_switch(pool):
    with patch.object(engine,'call_model',side_effect=engine.ProviderError(401,0,'bigmodel')) as call:
        with pytest.raises(engine.ProviderError):app.request_analysis(pool,'one',{},100,{'bigmodel':'fake','deepseek':'fake'},5)
        assert call.call_count==1


def test_paid_fallback_cannot_bypass_budget(pool):
    with patch.object(engine,'call_model',side_effect=engine.ProviderError(429,60,'bigmodel')) as call:
        with pytest.raises(ValueError,match='预算'):app.request_analysis(pool,'one',{},100,{'bigmodel':'fake','deepseek':'fake'},0.000001)
        assert call.call_count==1


def test_fallback_cache_and_persisted_cooldown(pool):
    prompt=engine.judgment_prompt({'id':'S1','source':'test','content':'证据'})
    def model(key,prompt,max_tokens,provider='deepseek'):
        if provider=='bigmodel':raise engine.ProviderError(503,60,provider)
        return reply(judgment('证据'))
    with patch.object(engine,'call_model',side_effect=model):
        app.request_analysis(pool,'judge:S1',prompt,100,{'bigmodel':'fake','deepseek':'fake'},5)
    assert app.cached_judgment(pool,'judge:S1',prompt,'证据',.7)['opportunity']==1
    app.PROVIDER_COOLDOWNS.clear()
    assert app.provider_cooldown('bigmodel')>0


@pytest.mark.parametrize('prompt_tokens,completion_tokens',[(-10,10),(10,-1),(True,10),(10,False)])
def test_invalid_token_usage_keeps_reservation_and_rejects_response(pool,prompt_tokens,completion_tokens):
    response=reply({})
    response['usage']={'prompt_tokens':prompt_tokens,'completion_tokens':completion_tokens}
    with patch.object(engine,'call_model',return_value=response):
        with pytest.raises(ValueError,match='用量'):
            app.request_provider(pool,'invalid-usage',{},100,'synthetic-key',5,'deepseek')
    state=app.analysis_state(pool)
    assert state['estimated_cost_yuan']==0 and state['unconfirmed_reserve_yuan']>0
    with app.connect() as db:
        row=db.execute('select estimated_cost from model_calls where batch_id=?',(pool,)).fetchone()
    assert row[0]>0
