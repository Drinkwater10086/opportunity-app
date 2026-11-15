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


def test_different_inputs_and_insufficient_common_candidates_are_explicit():
    a=result();b=deepcopy(a);b['input_sha256']='different'
    assert compare(a,b)['ari_on_common_candidates'] is None
    b=deepcopy(a)
    for rid in ['S2','S3']:b['judgments'][rid]['opportunity']=0
    b['clusters']=[{'records':['S1']}]
    assert compare(a,b)['ari_on_common_candidates'] is None
