import json
from unittest.mock import patch
import pytest
import app
import analysis_engine as engine
from test_pipeline import client, collect, judgment


def reply(data):
    return {'model':'test','usage':{'prompt_tokens':10,'completion_tokens':10},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}


def negative():
    d=judgment('')
    d.update(relevant=False,real_need=False,confidence=.1,function='',industry='',pain='',target_user='',need_kind='none')
    return d


@pytest.mark.parametrize('length',[16000,16001,19551,174000])
def test_segments_cover_full_text_with_bounded_overlap(length):
    text=('甲乙丙😀'*((length+3)//4))[:length]
    parts=engine.split_record(text)
    assert parts[0]['start']==0 and parts[-1]['end']==length
    rebuilt=parts[0]['content']
    for prev,part in zip(parts,parts[1:]):
        assert prev['end']-part['start']==500
        rebuilt+=part['content'][500:]
    assert rebuilt==text
    assert all(p['content']==text[p['start']:p['end']] and len(p['content'])<=16000 for p in parts)


def test_long_record_resume_reuses_completed_parts_and_sees_tail(client):
    bid=collect(client)
    text='普通背景。'*3400+'尾部真实需求'
    with app.connect() as db:
        db.execute('UPDATE records SET content=? WHERE batch_id=? AND id=?',(text,bid,'S00001'))
    seen=[]
    def first(key,prompt,max_tokens):
        seen.append(prompt)
        if prompt.get('segment',{}).get('index')==2:raise engine.ProviderError(503,0)
        return reply(negative())
    with patch.object(engine,'call_model',side_effect=first):
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==202
    state=app.analysis_state(bid)
    assert state['status']=='failed' and 'S00001' not in state['judgments']
    resumed=[]
    def second(key,prompt,max_tokens):
        resumed.append(prompt)
        d=negative()
        if 'evidence_passages' in prompt:
            for field in engine.EVIDENCE_FIELDS:
                d.pop(field);d[field+'_id']=''
        return reply(d)
    with patch.object(engine,'call_model',side_effect=second):
        assert client.post(f'/api/batches/{bid}/analyze',json={}).status_code==202
    state=app.analysis_state(bid)
    assert state['status']=='complete',state['error']
    assert not any(p.get('segment',{}).get('index')==1 for p in resumed)
    assert any('尾部真实需求' in p.get('content','') or any('尾部真实需求' in x['text'] for x in p.get('evidence_passages',[])) for p in resumed)
    merges=[p for p in resumed if p['task']=='汇总分段机会判别']
    assert len(merges)==1 and len(merges[0]['segment_assessments'])==2
    assert 'content' not in merges[0]
    assert state['judgments']['S00001']['long_text']['segment_count']==2
    assert len(state['judgments'])==2


def test_hierarchical_merge_includes_all_parts(client):
    bid=collect(client)
    text='长记录正文。'*30000
    with app.connect() as db:
        db.execute('UPDATE records SET content=? WHERE batch_id=? AND id=?',(text,bid,'S00001'))
    calls=[]
    def model(key,prompt,max_tokens):
        calls.append(prompt)
        return reply(negative())
    with patch.object(engine,'call_model',side_effect=model):
        client.post(f'/api/batches/{bid}/analyze',json={})
    assert app.analysis_state(bid)['status']=='complete'
    parts=[p for p in calls if 'segment' in p]
    assert len(parts)==len(engine.split_record(text))
    assert parts[-1]['segment']['end']==len(text)
    merges=[p for p in calls if 'segment_assessments' in p]
    assert all(len(p['segment_assessments'])<=4 for p in merges)
    assert merges[-1]['segment_assessments'][0]['start']==0
    assert merges[-1]['segment_assessments'][-1]['end']==len(text)


def test_overlong_model_quote_gets_one_logged_correction(client):
    bid=collect(client)
    seen=[]
    def model(key,prompt,max_tokens):
        seen.append(prompt)
        d=negative()
        if 'format_correction' not in prompt:d['evidence']='x'*16001
        if 'evidence_passages' in prompt:
            for field in engine.EVIDENCE_FIELDS:
                d.pop(field);d[field+'_id']=''
        return reply(d)
    with patch.object(engine,'call_model',side_effect=model):
        client.post(f'/api/batches/{bid}/analyze',json={})
    a=app.analysis_state(bid)
    assert a['status']=='complete'
    assert len(a['calls'])==4
    assert sum('format_correction' in p for p in seen)==2
    assert sum(c['stage'].endswith(':evidence_refs_v1') for c in a['calls'])==2


def test_long_verbatim_quote_kept_without_truncation():
    text='真实原文内容。'*100
    d=judgment(text)
    for field in ('need_evidence','user_evidence','ai_evidence','feasibility_evidence'):
        d[field]='真实原文内容。'
    result=engine.validate_judgment(d,text,.7)
    assert result['evidence']==text


def test_model_cannot_override_derived_opportunity():
    data=negative()
    data.update(opportunity=1, evidence_gate_failures=[])
    result=engine.validate_judgment(data,'正文',.7)
    assert result['opportunity']==0
    assert result['evidence_gate_failures']
    assert data['opportunity']==1
    data['unexpected_field']=True
    with pytest.raises(ValueError):
        engine.validate_judgment(data,'正文',.7)


def test_references_resolve_only_known_exact_original_spans():
    text='前文。需要AI批改作业。后文。'*100
    p=engine.reference_prompt(engine.judgment_prompt({'id':'S1','source':'test','content':text}),text)
    d=negative()
    for f in engine.EVIDENCE_FIELDS:
        d.pop(f);d[f+'_id']='E0001'
    resolved=engine.resolve_references(d,p,text)
    assert resolved['evidence']==text[:500]
    d['evidence_id']='E9999'
    with pytest.raises(ValueError):engine.resolve_references(d,p,text)
    d['evidence_id']='E0001';d['evidence']='made up'
    with pytest.raises(ValueError):engine.resolve_references(d,p,text)


def test_reference_merge_uses_only_supplied_evidence():
    text='开始。'+('无关文字'*10000)+'需要AI批改作业'
    nodes=[{'start':0,'end':len(text),'judgment':judgment('需要AI批改作业')}]
    p=engine.reference_prompt(engine.merge_judgment_prompt({'id':'S1','source':'test','content':text},'教育',nodes),text)
    assert len(p['evidence_passages'])==1
    assert p['evidence_passages'][0]['text']=='需要AI批改作业'
    assert 'content' not in p


def test_merge_excludes_rejected_child_quotes():
    text='真实原文'
    d=negative();d['evidence']=text;d['need_evidence']='模型改写的非原文'
    child=engine.validate_judgment(d,text,.7)
    assert child['opportunity']==0
    nodes=[{'start':0,'end':len(text),'judgment':child}]
    p=engine.reference_prompt(engine.merge_judgment_prompt({'id':'S1','source':'test','content':text},'办公',nodes),text)
    assert [part['text'] for part in p['evidence_passages']]==[text]


def test_truncated_reply_gets_bounded_reference_correction(client):
    b=collect(client)
    def model(key,prompt,max_tokens):
        d=negative()
        if 'evidence_passages' not in prompt:
            result=reply(d);result['choices'][0]['finish_reason']='length';return result
        for field in engine.EVIDENCE_FIELDS:
            d.pop(field);d[field+'_id']=''
        return reply(d)
    with patch.object(engine,'call_model',side_effect=model) as call:
        client.post(f'/api/batches/{b}/analyze',json={})
        assert call.call_count==4
    assert app.analysis_state(b)['status']=='complete'
