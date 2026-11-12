"""Deterministic pagination, concurrent execution and budget safety tests."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
import app
import sources
import analysis_engine as engine
from test_pipeline import client, collect, model_fixture


def test_pagination_multi_query_deduplicates_and_bounds():
    pages=[]
    def fetch(source,query,limit,days,page,window_end=None):
        pages.append((query,limit,page))
        return [{"url":f"https://example.test/{(page-1)*limit+i}"} for i in range(limit)], {"total_count":1000,"has_more":None,"params":{"page":page}}
    with patch.object(sources,'fetch_page',side_effect=fetch):
        rows,meta=sources.fetch('github','first\nsecond\nfirst',150,730)
    assert len(rows)==150
    assert pages==[('first',100,1),('first',100,2),('second',100,1),('second',100,2)]
    assert meta['complete'] and len(meta['pages'])==4


def test_pagination_preserves_partial_data():
    with patch.object(sources,'fetch_page',side_effect=[([{'url':'https://example.test/1'}],{'has_more':True}),ValueError('rate limited')]):
        rows,meta=sources.fetch('stackoverflow','test',200,365)
    assert len(rows)==1 and not meta['complete'] and meta['error']=='rate limited'


def test_query_bounds():
    assert sources.queries('alpha\nalpha\n beta')==['alpha','beta']
    for value in ('a','\n','x'*161,'\n'.join('term'+str(i) for i in range(9))):
        with pytest.raises(ValueError):sources.queries(value)


def test_two_records_really_overlap(client):
    bid=collect(client)
    barrier=threading.Barrier(2,timeout=5)
    def model(key,prompt,max_tokens):
        if prompt['task']=='逐条机会判别':barrier.wait()
        return model_fixture(key,prompt,max_tokens)
    with patch.object(engine,'call_model',side_effect=model):
        client.post(f'/api/batches/{bid}/analyze',json={'concurrency':2})
    state=app.analysis_state(bid)
    assert state['status']=='complete',state['error']
    assert len(state['judgments'])==2


def test_parallel_failure_saves_other_completed_record(client):
    bid=collect(client)
    barrier=threading.Barrier(2,timeout=5)
    def model(key,prompt,max_tokens):
        barrier.wait()
        if prompt['record_id']=='S00001':raise ValueError('specific failure')
        return model_fixture(key,prompt,max_tokens)
    with patch.object(engine,'call_model',side_effect=model):
        client.post(f'/api/batches/{bid}/analyze',json={'concurrency':2})
    state=app.analysis_state(bid)
    assert state['status']=='failed' and state['error']=='specific failure'
    assert list(state['judgments'])==['S00002']
    with patch.object(engine,'call_model',side_effect=model_fixture) as call:
        client.post(f'/api/batches/{bid}/analyze',json={'concurrency':1})
    assert app.analysis_state(bid)['status']=='complete'
    assert call.call_count==2


def test_parallel_budget_reservation_is_atomic(client):
    bid=collect(client)
    with app.connect() as db:
        db.execute("INSERT INTO analyses(batch_id,status,config) VALUES (?,'running',?)",(bid,json.dumps({'provider':'deepseek'})))
    prompt={'test':'budget'}
    encoded=json.dumps({'system':engine.system_prompt('deepseek'),'user':prompt},ensure_ascii=False)
    reserve=((len(encoded.encode('utf-8'))+1024)*2+100*8)/1_000_000
    release=threading.Event()
    start=threading.Barrier(2,timeout=5)
    def model(*args):
        assert release.wait(5)
        return {'usage':{'prompt_tokens':10,'completion_tokens':10},'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
    def request(i):
        start.wait()
        try:return app.request_analysis(bid,str(i),prompt,100,'fake',reserve*1.5)
        except ValueError:
            release.set();return 'blocked'
    with patch.object(engine,'call_model',side_effect=model) as call, ThreadPoolExecutor(2) as pool:
        results=list(pool.map(request,[1,2]))
    assert results.count('blocked')==1 and call.call_count==1


@pytest.mark.parametrize('workers',[8,32])
def test_high_concurrency_completes_without_lost_results(client,workers):
    from test_pipeline import source_fixture
    template=source_fixture('github','test',1,90)[0][0]
    items=[{**template,'title':f'{i} synthetic','url':f'https://github.com/example/{i}'} for i in range(workers)]
    with patch.object(app.sources,'fetch',return_value=(items,{'returned_count':workers})):
        response=client.post('/api/batches',json={'direction':'test','query':'test','sources':['github']})
    bid=response.json()['id']
    barrier=threading.Barrier(workers,timeout=15)
    def model(key,prompt,max_tokens):
        if prompt['task']=='逐条机会判别':barrier.wait()
        return model_fixture(key,prompt,max_tokens)
    with patch.object(engine,'call_model',side_effect=model):
        client.post(f'/api/batches/{bid}/analyze',json={'concurrency':workers})
    state=app.analysis_state(bid)
    assert state['status']=='complete',state['error']
    assert len(state['judgments'])==workers
    assert len(state['calls'])==workers+1


def test_concurrency_bounds():
    assert app.AnalysisInput(concurrency=32).concurrency==32
    for value in (0,33):
        with pytest.raises(ValueError):app.AnalysisInput(concurrency=value)
