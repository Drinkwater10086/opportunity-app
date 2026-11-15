from local_analysis import screening_flow


def judgment(**changes):
    return {**{k:True for k in ('quality','relevant','real_need','context','ai_core','feasible','classified')},
            'excluded':False,'confidence':.8,'opportunity':1,**changes}


def test_flow_disjoint_losses_reconcile_with_decisions():
    rows={'A':judgment(quality=False,opportunity=0),
          'B':judgment(relevant=False,opportunity=0),
          'C':judgment(real_need=False,opportunity=0),
          'D':judgment(confidence=.65,opportunity=0),
          'E':judgment(excluded=True,opportunity=0),'F':judgment()}
    result=screening_flow(rows,.7)
    assert [s['remaining'] for s in result['stages']]==[5,4,3,3,3,3,3,2,1]
    removed=[rid for s in result['stages'] for rid in s['removed_ids']]
    assert len(removed)==len(set(removed))==5
    assert result['final_ids']==['F'] and result['matches_decisions']
    assert rows['A']['quality'] is False


def test_empty_flow_and_inconsistent_saved_decision_are_explicit():
    assert screening_flow({},.7)['final_ids']==[]
    assert screening_flow({},.7)['matches_decisions']
    assert not screening_flow({'A':judgment(opportunity=0)},.7)['matches_decisions']
