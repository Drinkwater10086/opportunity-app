from copy import deepcopy
from local_comparison import compare


def result():
    return {'version':'test','input_sha256':'same',
            'judgments':{rid:{'opportunity':1} for rid in ['S1','S2','S3']},
            'clusters':[{'records':['S1','S2']},{'records':['S3']}]}


def test_common_candidate_ari_does_not_hide_changed_screening():
    a=result();b=deepcopy(a)
    b['judgments']['S3']['opportunity']=0
    b['judgments']['S4']={'opportunity':1}
    b['clusters']=[{'records':['S1','S2','S4']}]
    report=compare(a,b)
    assert report['ari_on_common_candidates']==1
    assert report['added_ids']==['S4'] and report['removed_ids']==['S3']
    assert report['common_candidates']==2
    assert report['candidate_jaccard']==.5 and report['union_candidates']==4
    assert report['warnings']


def test_different_inputs_and_insufficient_common_candidates_are_explicit():
    a=result();b=deepcopy(a);b['input_sha256']='different'
    assert compare(a,b)['ari_on_common_candidates'] is None
    assert compare(a,b)['candidate_jaccard'] is None
    b=deepcopy(a)
    for rid in ['S2','S3']:b['judgments'][rid]['opportunity']=0
    b['clusters']=[{'records':['S1']}]
    assert compare(a,b)['ari_on_common_candidates'] is None


def test_ari_rejects_duplicate_missing_extra_and_empty_cluster_members():
    a=result()
    for clusters in [[{'records':['S1','S2','S3']},{'records':['S1']}],
                     [{'records':['S1','S2']}],
                     [{'records':['S1','S2','S3','S4']}],
                     [{'records':['S1','S2','S3']},{'records':[]}]]:
        b=deepcopy(a);b['clusters']=clusters
        report=compare(a,b)
        assert not report['right_partition_valid']
        assert report['ari_on_common_candidates'] is None
        assert report['candidate_jaccard']==1


def test_empty_sets_disjoint_sets_and_trivial_agreement_are_distinguished():
    empty={'version':'test','input_sha256':'same','judgments':{},'clusters':[]}
    report=compare(empty,empty)
    assert report['candidate_jaccard'] is None
    assert report['ari_on_common_candidates'] is None
    a=result();b=deepcopy(a)
    b['judgments']={'S4':{'opportunity':1}};b['clusters']=[{'records':['S4']}]
    assert compare(a,b)['candidate_jaccard']==0
    a['clusters']=[{'records':[rid]} for rid in a['judgments']]
    a['config']={}
    report=compare(a,a)
    assert report['candidate_jaccard']==1 and report['ari_on_common_candidates']==1
    assert len(report['warnings'])==3
