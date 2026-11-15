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


@pytest.mark.parametrize('prefix',['may','might','could','possibly','perhaps'])
def test_tentative_need_is_not_asserted_demand(prefix):
    text=f'Our team {prefix} need AI meeting transcription using a Whisper model API.'
    result=judge(text)
    assert result['opportunity']==0
    assert not result['real_need']
    assert result['content_context']['tentative_need_spans']
    assert result['content_context']['record_tentative_need_spans']
    for span in result['content_context']['tentative_need_spans']:
        assert text[span['start']:span['end']]==span['text']


def test_tentative_sentence_does_not_remove_separate_actual_request():
    text='Our team might need storage someday. We need AI meeting transcription using a Whisper API.'
    assert judge(text)['opportunity']==1
    cues=judge(text)['content_context']['record_tentative_need_spans']
    assert cues and 'might' in cues[0]['prefix_text']
    # Could modifies the proposed solution/question, not the asserted need.
    assert judge('Could our team use a Whisper AI model API? We need meeting transcription.')['opportunity']==1
    assert judge('我们团队可能需要AI会议转写，技术方案为现有Whisper模型API和本地文档。')['opportunity']==0
    assert judge('我们团队需要AI会议转写，技术方案为现有Whisper模型API和本地文档。')['opportunity']==1


def test_singleton_name_is_exact_traceable_source_excerpt():
    record={'id':'S1','title':'Split PDF transcripts into speaker turns','content':'body'}
    result=core.topic_name([record],record,[{'term':'correct'}],'图像识别')
    span=result['name_evidence']
    assert result['name']=='原文标题：'+record['title']
    assert record[span['field']][span['start']:span['end']]==span['text']
    record={**record,'title':'','content':'需求'*150}
    result=core.topic_name([record],record,[],'文本生成')
    assert result['name'].endswith('…')
    assert result['name_evidence']['end']==180


def test_mixed_chinese_ai_boundaries_do_not_match_english_substrings():
    import re
    for text in ['使用AI会议转写','调用Whisper模型','通过OCR识别文档','使用GPT4处理邮件']:
        assert re.search(core.PATTERNS['ai'],text,re.I)
    for text in ['email','storage','chair','staircase','whispering','neuralgia','OCRing','my_AI_module']:
        assert not re.search(core.PATTERNS['ai'],text,re.I)


def test_structured_hiring_ads_are_not_application_demand():
    texts=[
        'Our team needs AI meeting transcription using a Whisper model API. Job ID 123. Apply now.',
        'Our team needs AI meeting transcription using a Whisper model API. We are hiring. Salary negotiable.',
        '团队需要AI会议转写，现有Whisper模型API可用。招聘岗位：开发工程师；投递简历至公司平台。',
    ]
    for text in texts:
        result=judge(text)
        assert result['opportunity']==0
        assert 'job_posting' in result['hard_gate_failures']
        status=result['content_context']['job_posting']
        assert status['exclude']
        for s in status['signals'].values():
            if s:assert text[s['start']:s['end']]==s['text']


def test_recruiting_software_requests_are_not_blanket_excluded():
    text='Our team needs AI to extract job posting data for meetings using a model API. Job ID 123. Apply now.'
    assert judge(text)['opportunity']==1
    assert judge('Our team cannot classify job applications using a Whisper AI model API for meeting reports. Job ID 123. Apply now.')['opportunity']==1
    assert judge('Our team needs AI meeting transcription for recruiting using a Whisper model API.')['opportunity']==1


def test_hiring_signals_outside_selected_window_remain_traceable():
    text='Our team needs AI meeting transcription using a Whisper model API.\n\n'+('Background information. '*80)+'Job ID 123. Apply now.'
    result=judge(text)
    assert result['opportunity']==0
    cue=result['content_context']['job_posting']['signals']['position']
    assert cue['start']>result['selected_context']['end']
    assert text[cue['start']:cue['end']]==cue['text']
