"""Synthetic contrasts test scoring behavior, never claim real-data accuracy."""
from local_routes import LocalConfig
import local_analysis as core
import pytest


def judge(text,**config):
    return core.judge({'id':'S1','title':'test','content':text,'source':'test'},'企业办公自动化',LocalConfig(**config).model_dump())


def test_complete_conditions_can_have_distinct_scores():
    strong=judge('Our team is looking for AI meeting transcription using a Whisper model API.')
    weak=judge('Manual meeting workflow uses an AI model API for documents.')
    assert strong['gate_passed'] and weak['gate_passed']
    assert strong['rule_completeness']==weak['rule_completeness']==1
    assert 0<=weak['confidence']<strong['confidence']<1
    assert strong['opportunity']==1
    assert weak['opportunity']==0 and 'below_threshold' in weak['failed_checks']
    assert strong['need_kind']=='explicit_request' and weak['need_kind']=='weak_signal'


def test_component_evidence_offsets_reference_original_record():
    text='Preface without demand.\n\nOur team is looking for AI meeting transcription using a Whisper model API.'
    result=judge(text)
    for factor in result['score_detail']['components'].values():
        for span in factor['evidence']:
            assert text[span['start']:span['end']]==span['text']
            assert span['start']>=result['selected_context']['start']
    assert result['score_detail']['components']['classified']['matched_terms']


def test_threshold_monotonicity_and_context_selection_independence():
    text='Our team needs AI meeting transcription using a Whisper model API.\n\nOur team is looking for AI meeting transcription using a Whisper API.'
    results=[judge(text,threshold=t) for t in [.5,.7,.85,.95]]
    assert len({j['confidence'] for j in results})==1
    assert len({j['selected_context']['start'] for j in results})==1
    assert [j['opportunity'] for j in results]==sorted([j['opportunity'] for j in results],reverse=True)
    assert results[0]['selected_context']['start']>0


def test_non_opportunity_missing_conditions_and_exclusions_have_explicit_caps():
    incomplete=judge('Our team is looking for meeting transcription using an API.')
    ad=judge('Our team needs AI meeting transcription using Whisper model API. Buy now!')
    assert incomplete['confidence']<=.49 and incomplete['opportunity']==0
    assert ad['confidence']<=.2 and ad['opportunity']==0
    assert ad['score_detail']['raw_evidence_score']>ad['confidence']


def test_legacy_completeness_is_an_explicit_comparison_method():
    text='Our team needs AI meeting transcription using a Whisper model API.'
    old=judge(text,score_method='completeness')
    new=judge(text)
    assert old['confidence']==1 and old['opportunity']==1
    assert new['confidence']<1 and new['opportunity']==1
    assert old['selected_context']['text']==new['selected_context']['text']
    with pytest.raises(ValueError):LocalConfig(score_method='unsupported')


def test_automatic_threshold_counts_are_not_conditioned_on_current_threshold():
    rows=[{'id':'S1','title':'meeting','source':'test',
           'content':'Our team needs AI meeting transcription using a Whisper model API.'}]
    result=core.analyze({'direction':'企业办公自动化'},rows,LocalConfig(threshold=.95).model_dump(),1)
    assert result['candidate_count']==0
    counts={r['threshold']:r['candidate_count'] for r in result['evaluation']['threshold_sensitivity']}
    assert counts[.7]==1 and counts[.95]==0
