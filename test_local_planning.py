from local_planning import Plan,render,LABELS
import pytest


def test_planning_contains_required_sections_without_fabricating_evidence():
    cluster={'name':'Meeting','records':['S1'],'priority':1,'score':60,'count':1,'sources':['GitHub']}
    result={'input_records':[{'id':'S1','source':'GitHub','url':'https://github.com/example/1','collected_at':'2026-11-15'}],
            'judgments':{'S1':{'need_evidence':'Need meeting notes.','user_evidence':'Our team.','feasibility_evidence':'Whisper API.'}},
            'score_formula':'test formula','version':'test','input_sha256':'hash'}
    plan=Plan(schedule='团队估计：两周，待验证',core_features='候选功能：转写').model_dump()
    text=render('B1','L1',cluster,result,plan,'P1')
    for title in LABELS.values():assert title in text
    assert 'Need meeting notes.' in text and 'https://github.com/example/1' in text
    assert '待团队补充' in text and '团队估计：两周，待验证' in text
    assert 'hash' in text and 'P1' in text
    with pytest.raises(ValueError):Plan(schedule='x'*4001)
