"""Score mechanics and tie transparency; not market-value validation."""
from copy import deepcopy

from analysis_engine import rank_clusters
from local_value import diagnostics, source_removal


def test_weight_tradeoff_and_formal_score_preservation():
    records=[{'id':str(i),'source':'A' if i<11 else 'B'} for i in range(12)]
    groups=[{'records':[str(i) for i in range(10)]},{'records':['10','11']}]
    clusters=rank_clusters(groups,records,2,(.6,.4))
    original=deepcopy(clusters);d=diagnostics(clusters,2,(.6,.4))
    scale=next(row for row in d['weight_grid'] if row['coverage_weight']==0)
    coverage=next(row for row in d['weight_grid'] if row['coverage_weight']==1)
    assert scale['top_ids']==['C1']
    assert coverage['top_ids']==['C2']
    actual=next(row for row in d['weight_grid'] if row['coverage_weight']==.6)
    assert actual['scores']=={c['id']:c['score'] for c in clusters}
    assert clusters==original


def test_all_ties_list_all_leaders_without_implying_preference():
    clusters=rank_clusters([{'records':['1']},{'records':['2']}],
                          [{'id':'1','source':'A'},{'id':'2','source':'B'}],2,(.6,.4))
    d=diagnostics(clusters,2,(.6,.4))
    assert d['all_scores_equal']
    assert d['tie_groups'][0]['cluster_ids']==['C1','C2']
    assert all(row['top_ids']==['C1','C2'] for row in d['weight_grid'])
    assert diagnostics([],2,(.6,.4))['weight_grid']==[]
    assert not diagnostics(clusters[:1],2,(.6,.4))['all_scores_equal']


def test_source_removal_exposes_ranking_reversal_without_mutating_formal_results():
    rows=[{'id':str(i),'source':'A' if i<11 else 'B'} for i in range(12)]
    clusters=rank_clusters([{'records':[str(i) for i in range(10)]},{'records':['10','11']}],rows,2,(.6,.4))
    before=deepcopy(clusters)
    result=diagnostics(clusters,2,(.6,.4),rows)['source_removal']
    assert result['baseline_top_ids']==['C2']
    without_b=next(r for r in result['scenarios'] if r['removed_source']=='B')
    assert without_b['top_ids']==['C1'] and without_b['remaining_source_denominator']==1
    assert next(r for r in without_b['themes'] if r['id']=='C1')['score']==100
    assert result['ranking_change_scenario_count']==result['comparable_scenario_count']==1
    assert next(t for t in result['themes'] if t['id']=='C2')['maximum_rank_drop']==1
    assert next(t for t in result['themes'] if t['id']=='C1')['disappears_when_removing']==['A']
    assert clusters==before


def test_source_removal_ties_and_disappearance_are_not_invented_rank_changes():
    rows=[{'id':'1','source':'A'},{'id':'2','source':'B'}]
    clusters=rank_clusters([{'records':['1']},{'records':['2']}],rows,2,(.6,.4))
    result=source_removal(clusters,rows,2,(.6,.4))
    assert result['baseline_top_ids']==['C1','C2']
    assert result['ranking_change_scenario_count'] is None and result['comparable_scenario_count']==0
    assert all(t['baseline_rank']==1 for t in result['themes'])
    assert all(t['maximum_rank_drop']==0 for t in result['themes'])
    for case in result['scenarios']:
        missing=next(t for t in case['themes'] if t['remaining_count']==0)
        assert missing['score'] is None and missing['rank'] is None and missing['rank_change'] is None


def test_source_removal_single_source_and_empty_inputs_are_not_stable_scores():
    rows=[{'id':'1','source':'A'}]
    clusters=rank_clusters([{'records':['1']}],rows,1,(.6,.4))
    result=source_removal(clusters,rows,1,(.6,.4))
    assert result['status']=='single_source' and result['ranking_change_scenario_count'] is None
    assert not result['scenarios'][0]['ranking_available']
    assert result['themes'][0]['maximum_rank_drop'] is None
    assert source_removal([],[],1,(.6,.4))['status']=='no_candidates'
    assert diagnostics(clusters,1,(.6,.4))['source_removal']['status']=='unavailable'


def test_source_removal_uses_selected_platform_denominator_and_rejects_broken_membership():
    rows=[{'id':'1','source':'A'},{'id':'2','source':'B'}]
    clusters=rank_clusters([{'records':['1','2']}],rows,3,(.6,.4))
    result=source_removal(clusters,rows,3,(.6,.4))
    assert all(case['remaining_source_denominator']==2 for case in result['scenarios'])
    assert all(case['themes'][0]['score']==70 for case in result['scenarios'])
    assert source_removal(clusters,rows,1,(.6,.4))['status']=='invalid_sources'
    broken=deepcopy(clusters);broken[0]['records'].append('1')
    assert source_removal(broken,rows,3,(.6,.4))['status']=='invalid_partition'
