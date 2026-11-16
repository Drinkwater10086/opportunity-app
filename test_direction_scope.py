from local_routes import LocalConfig
from local_analysis import direction_scope,judge


def row(text):return {'id':'S1','title':'request','content':text,'source':'test'}


def test_chinese_industry_direction_can_match_declared_english_aliases():
    cfg=LocalConfig().model_dump()
    result=judge(row('Our customers need an AI chatbot for an ecommerce store, using a language model API.'),'电商',cfg)
    assert result['opportunity']==1
    assert result['direction_scope']['profile']=='电商'
    assert 'ecommerce' in result['scope_terms']
    assert direction_scope('AI retail applications',cfg)['profile']=='零售'
    assert direction_scope('research',cfg)['profile']=='科研'


def test_explicit_terms_override_office_expansion():
    cfg=LocalConfig(direction_terms='meeting').model_dump()
    result=judge(row('Our team needs AI email extraction using an OCR model API.'),'企业办公自动化',cfg)
    assert not result['opportunity'] and not result['relevant']
    assert result['direction_scope']['mode']=='explicit'
    assert result['direction_scope']['expanded_terms']==[]
    positive=judge(row('Our team needs AI meeting transcription using a Whisper model API.'),'企业办公自动化',cfg)
    assert positive['opportunity']==1


def test_extra_business_qualifiers_are_not_silently_discarded():
    cfg=LocalConfig().model_dump()
    for direction in ['金融反诈','电商客服','办公合同审查','教育研究']:
        scope=direction_scope(direction,cfg)
        assert scope['mode']=='literal' and not scope['expanded_terms']
    assert direction_scope('企业办公自动化',cfg)['mode']=='office_profile'
    assert direction_scope('AI教育应用',cfg)['profile']=='教育'


def test_scope_evidence_uses_same_boundary_as_relevance_check():
    text='myecommerce notes. Our customers need an AI chatbot for ecommerce using a language model API.'
    result=judge(row(text),'电商',LocalConfig().model_dump())
    assert result['opportunity']==1
    evidence=result['score_detail']['components']['relevant']['evidence']
    assert any(e['start']==text.index('ecommerce',text.index('Our')) for e in evidence)
    assert all(text[e['start']:e['end']]==e['text'] for e in evidence)



def test_general_ai_direction_matches_english_terms_without_losing_qualifiers():
    config=LocalConfig().model_dump()
    texts=['Our team needs AI meeting transcription using a Whisper model API.',
           'Our team needs artificial intelligence for email extraction using a model API.',
           'Our team needs GPT4 for email extraction using a model API.']
    for text in texts:
        result=judge(row(text),'人工智能',config)
        assert result['direction_scope']['mode']=='ai_profile' and result['opportunity']==1
    assert direction_scope('artificial intelligence',config)['mode']=='ai_profile'
    assert direction_scope('AI applications',config)['mode']=='ai_profile'
    assert direction_scope('人工智能医疗',config)['profile']=='医疗'
    assert direction_scope('人工智能合同审查',config)['mode']=='literal'
    assert not judge(row(texts[0]),'人工智能医疗',config)['relevant']
    assert not judge(row('Our team needs email storage and manual reports.'),'人工智能',config)['relevant']
    explicit=LocalConfig(direction_terms='contract').model_dump()
    assert direction_scope('人工智能',explicit)['mode']=='explicit'
    assert not judge(row(texts[0]),'人工智能',explicit)['relevant']
