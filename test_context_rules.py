"""Synthetic negation and genre contrasts; not a real-data accuracy benchmark."""
import pytest
from local_routes import LocalConfig
import local_analysis as core


def judge(text):
    return core.judge({'id':'S1','title':'test','content':text,'source':'test'},'企业办公自动化',LocalConfig().model_dump())


@pytest.mark.parametrize('text',[
    'Our team does not need AI meeting transcription using a Whisper model API.',
    'Our team does not need meeting transcription using a Whisper AI model API.',
    "Our team doesn't need AI meeting transcription with a Whisper API.",
    'Our team no longer needs AI meeting transcription with a Whisper API.',
    'Our team has no problem using Whisper AI meeting transcription model API.',
    '我们不再需要AI会议转写，现有Whisper模型API已经够用。',
])
def test_explicit_negated_need_is_not_an_opportunity(text):
    result=judge(text)
    assert result['opportunity']==0
    assert result['content_context']['denied_need_spans']
    for span in result['content_context']['denied_need_spans']:
        assert text[span['start']:span['end']]==span['text']


def test_denial_of_one_need_does_not_remove_a_separate_affirmative_request():
    text='Our team does not need document storage, but is looking for AI meeting transcription using a Whisper API.'
    assert judge(text)['opportunity']==1
    assert judge('Our team not only needs AI meeting transcription but also action items using Whisper API.')['opportunity']==1


def test_tutorial_exclusion_preserves_actual_user_difficulties():
    tutorial='This tutorial explains how to create AI meeting transcription using a Whisper model API for teams.'
    assert judge(tutorial)['opportunity']==0
    assert 'tutorial_content' in judge(tutorial)['hard_gate_failures']
    for phrase in ['a tutorial',"a beginner’s guide", "a beginner's guide"]:
        text=f'Our team followed {phrase} but cannot transcribe meetings using the Whisper AI model API.'
        assert judge(text)['opportunity']==1


def test_not_sponsored_does_not_trigger_ad_exclusion():
    text='Our team is looking for AI meeting transcription using a Whisper model API. Not sponsored.'
    assert judge(text)['opportunity']==1
    assert judge(text.replace('Not sponsored.','Sponsored.'))['opportunity']==0


def test_plural_office_terms_have_explicit_traceable_scope_hits():
    for term in ['meetings','emails','invoices']:
        result=judge(f'Our team needs AI transcription for {term} using a Whisper model API.')
        assert result['opportunity']==1
        assert term in result['scope_terms']
