from local_planning import Plan,render,LABELS,initial_drafts
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


def test_initial_draft_is_complete_explicitly_hypothetical_and_deterministic():
    from copy import deepcopy
    cluster={'id':'C1','name':'邮件自动化候选需求','function':'自动化流程','records':['S1']}
    result={'clusters':[cluster],'judgments':{'S1':{
        'user_evidence':'Our team.','need_evidence':'We need email extraction.','feasibility_evidence':'An API.'}}}
    original=deepcopy(result)
    drafts=initial_drafts(result)
    assert result==original and drafts==initial_drafts(result)
    draft=drafts['C1'];plan=Plan.model_validate(draft['plan'])
    assert all(plan.model_dump().values())
    assert draft['origin']=='program_initial_draft'
    assert 'S1原文线索' in plan.target_users and 'We need email extraction.' in plan.pain_points
    assert '估算' in plan.schedule and '实际工期' in plan.schedule
    assert '尚未实测' in plan.resources and '验收状态：待执行' in plan.validation
    assert 'S1' in draft['sample_ids']
