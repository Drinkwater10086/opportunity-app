"""Score mechanics and tie transparency; not market-value validation."""
from copy import deepcopy

from analysis_engine import rank_clusters
from local_value import diagnostics


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
