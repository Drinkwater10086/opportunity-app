from local_analysis import topic_name


def test_scenario_name_uses_exact_spans_in_selected_context():
    prefix='Unrelated introduction. '
    body='Our team needs email extraction into CRM using an AI model API.'
    record={'id':'S1','title':'Automating email and CRM','content':prefix+body}
    judgments={'S1':{'analysis_text':body,'selected_context':{'start':len(prefix)}}}
    result=topic_name([record],record,[],'自动化流程',judgments)
    assert result['name']=='邮件、CRM场景的自动化流程候选需求'
    assert [f['label'] for f in result['name_features']]==['邮件','CRM']
    for f in result['name_features']:
        for s in f['evidence']:assert record['content'][s['start']:s['end']]==s['text']


def test_minority_scene_is_not_promoted_as_a_shared_topic():
    records=[{'id':str(i),'title':'Issue','content':text} for i,text in enumerate([
        'AI meeting transcription','AI invoice extraction','AI knowledge base retrieval'])]
    result=topic_name(records,records[0],[{'term':'AI'}],'知识检索')
    assert not result['name_features']
    assert '会议' not in result['name'] and '发票' not in result['name']
    records[1]['content']='AI meeting reports'
    result=topic_name(records,records[0],[],'语音处理')
    assert result['name']=='会议场景的语音处理候选需求'
    assert result['name_features'][0]['support_count']==2


def test_english_substrings_cannot_invent_scenes_and_fallback_is_explicit():
    record={'id':'S1','title':'Original title','content':'emailing contractions in an officeholder reportable example'}
    result=topic_name([record],record,[],'文本生成')
    assert not result['name_features']
    assert result['name']=='原文标题：Original title'
