import json
from unittest.mock import patch
import pytest
import automatic_evaluation as ev
import analysis_engine as engine
import sources
from test_pipeline import judgment, client, collect, model_fixture


def report(texts, groups):
    return ev.evaluate(json.dumps({'records':[{'id':str(i),'content':t} for i,t in enumerate(texts)],
        'positive_ids':[str(i) for i in range(len(texts))],
        'clusters':[{'name':str(i),'records':[str(j) for j in g]} for i,g in enumerate(groups)]}))


def test_separated_clusters_score_better_than_mixed():
    texts=['会议录音语音转写', '会议录音语音转写', '农田灌溉土壤监测', '农田灌溉土壤监测']
    good=report(texts,[[0,1],[2,3]])
    bad=report(texts,[[0,2],[1,3]])
    assert good['silhouette'] > .9
    assert bad['silhouette'] < 0
    assert good['stability']['score'] is None


@pytest.mark.parametrize('texts,groups', [([],[]),(['会议'],[[0]]),(['会议','翻译'],[[0,1]]),
    (['会议','翻译'],[[0],[1]]),(['相同','相同','相同'],[[0,1],[2]]),(['','翻译','会议'],[[0,1],[2]])])
def test_undefined_scores_are_not_fabricated(texts,groups):
    r=report(texts,groups)
    assert r['silhouette'] is None and r['reason']


def test_duplicate_membership_rejected():
    r=report(['会议','翻译','分析'],[[0,1],[1,2]])
    assert not r['structure_valid'] and r['silhouette'] is None


@pytest.mark.parametrize('groups,texts', [([[0,1]],['会议','翻译']),
    ([[0],[1]],['会议','翻译']), ([[0,1],[2]],['相同','相同','相同'])])
def test_stability_is_independent_of_silhouette_eligibility(groups,texts):
    clusters=[{'name':str(i),'records':[str(j) for j in g]} for i,g in enumerate(groups)]
    data={'records':[{'id':str(i),'content':t} for i,t in enumerate(texts)],
          'positive_ids':[str(i) for i in range(len(texts))], 'clusters':clusters,
          'valid_runs':[clusters,clusters]}
    r=ev.evaluate(json.dumps(data))
    assert r['silhouette'] is None
    assert r['stability']['score']==1.0 and r['stability']['valid_runs']==2


def test_large_evaluation_does_not_allocate_quadratic_distance_matrix():
    n=ev.MAX_EXACT_SILHOUETTE_SAMPLES+1
    with patch.object(ev,'TfidfVectorizer',side_effect=AssertionError('must not allocate')):
        r=report(['会议记录']*n,[list(range(n//2)),list(range(n//2,n))])
    assert r['silhouette'] is None and r['sample_count']==n
    assert r['structure_valid'] and '保护' in r['reason']


def test_evidence_gate_blocks_vendor_and_unquoted_claims():
    text='会议记录使用语音识别'
    d=judgment(text)
    d['need_kind']='vendor_claim'
    result=engine.validate_judgment(d,text,.7)
    assert result['opportunity']==0 and result['evidence_gate_failures']
    d['need_kind']='explicit_request';d['need_evidence']='虚构的用户求助'
    result=engine.validate_judgment(d,text,.7)
    assert result['opportunity']==0
    assert result['need_evidence']=='虚构的用户求助'  # retain attempted evidence for audit


def test_report_endpoint_supports_unlabelled_completed_batch(client):
    b=collect(client)
    with patch.object(engine,'call_model',side_effect=model_fixture):
        client.post(f'/api/batches/{b}/analyze',json={})
    r=client.get(f'/api/batches/{b}/automatic-evaluation.json')
    assert r.status_code==200
    assert r.json()['structure_valid']
    assert r.json()['silhouette'] is None  # one cluster
    assert 'accuracy' not in r.json()


def test_github_issue_adapter_excludes_pull_requests_and_profiles():
    class Reply:
        status_code=200
        def raise_for_status(self): pass
        def json(self): return {'items':[
            {'title':'Need meeting notes','body':'Please add AI transcription contact test@example.com',
             'html_url':'https://github.com/example/tool/issues/1','created_at':'2026-11-01T00:00:00Z',
             'comments':4,'user':{'login':'private-profile-unused'}},
            {'pull_request':{},'title':'ignore'}], 'total_count':2}
    sources._cooldown.clear()
    with patch.object(sources.requests,'get',return_value=Reply()) as get:
        records,meta=sources.fetch('github_issues','meeting',10,90)
    assert len(records)==1
    assert 'test@example.com' not in records[0]['raw_text']
    assert 'user' not in records[0]
    assert 'is:issue' in get.call_args.kwargs['params']['q']
    assert sources.NAMES['github_issues']==sources.NAMES['github']


def test_singleton_explanation_does_not_change_numeric_score():
    r=report(['会议语音转写','会议语音转写','农田灌溉'],[[0,1],[2]])
    single=r['per_cluster'][1]
    assert single['singleton'] and single['silhouette']==0
    assert '不能单独评价' in single['interpretation']
    assert r['silhouette']==pytest.approx(2/3,abs=1e-6)
    assert r['conclusion'] and r['singleton_note']


def test_screening_reasons_overlap_without_double_counting_records():
    valid=engine.validate_judgment(judgment('原文'),'原文',.7)
    invalid=judgment('原文');invalid.update(relevant=False,real_need=False,confidence=.2,need_kind='none')
    invalid=engine.validate_judgment(invalid,'原文',.7)
    unquoted=judgment('原文');unquoted['need_evidence']='编造'
    unquoted=engine.validate_judgment(unquoted,'原文',.7)
    d=ev.screening_diagnostics({'a':valid,'b':invalid,'c':unquoted},.7)
    assert d['judged_count']==3 and d['candidate_count']==1 and d['rejected_count']==2
    assert d['evidence_only_rejected']==1 and d['no_signal_or_vendor_count']==1
    assert sum(r['count'] for r in d['reasons'])>d['rejected_count']


@pytest.mark.parametrize('relation',['indirect','outside'])
def test_scope_relation_overrides_conflicting_relevance(relation):
    d=judgment('原文');d['scope_relation']=relation
    r=engine.validate_judgment(d,'原文',.7,require_scope=True)
    assert not r['relevant'] and r['opportunity']==0


def test_new_scope_required_but_legacy_judgments_readable():
    d=judgment('原文');d.pop('scope_relation')
    with pytest.raises(ValueError,match='缺少研究方向'):
        engine.validate_judgment(d,'原文',.7,require_scope=True)
    assert engine.validate_judgment(d,'原文',.7)['opportunity']==1
