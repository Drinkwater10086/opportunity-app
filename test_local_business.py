"""Synthetic contrasts for business evidence; not collected competition data."""
from copy import deepcopy
from unittest.mock import patch
import numpy as np
import pytest
import local_analysis as core
import local_business
import local_cache
import local_embeddings
import local_recall
from local_routes import LocalConfig


def record(i=1,text=None):
    return {'id':f'S{i:05d}','source':'GitHub','title':'Meeting request',
            'content':text or 'Our team needs meeting transcription using a Whisper AI model API.'}


def judge(text):return core.judge(record(text=text),'企业办公自动化',LocalConfig().model_dump())


@pytest.mark.parametrize('text',[
    'Our team needs AI model API access for meeting reports. HTTP 503 is returned.',
    'Our team needs an AI model API for email reports but gets connection refused.',
    '我们的团队需要AI模型API处理会议报表，但出现接口报错和连接超时。',
])
def test_technical_incident_without_processing_task_is_separated(text):
    out=judge(text)
    assert out['business_profile']['technical_only']
    assert out['excluded'] and not out['opportunity']
    assert 'technical_incident' in out['failed_checks']


def test_incident_does_not_hide_an_explicit_business_processing_task():
    text='Our team needs AI to extract customer emails into reports using a model API. HTTP 503 sometimes interrupts this workflow.'
    out=judge(text)
    assert not out['business_profile']['technical_only']
    assert out['opportunity']==1
    for span in out['business_profile']['signals'].values():
        if span:assert text[span['start']:span['end']]==span['text']


def test_separate_passages_keep_offsets_without_fusing_missing_conditions():
    first='Our team needs meeting transcription using a Whisper AI model API.'
    second='Our team is looking for an AI model API to extract emails. Currently we manually process hundreds of emails every week.'
    text=first+'\n\n'+second
    out=judge(text)
    assert len(out['evidence_contexts'])==2
    for entry in out['evidence_contexts']:
        assert text[entry['start']:entry['end']]==entry['text']
        assert entry['gate_passed']
    for entry in out['business_contexts']:
        for span in entry['signals'].values():
            if span:assert text[span['start']:span['end']]==span['text']
    incomplete='Our team needs better meeting reports.\n\nAn unrelated benchmark uses a Whisper AI model API.'
    assert judge(incomplete)['opportunity']==0


def test_evidence_storage_bound_is_explicit_and_records_remain_complete():
    text='\n\n'.join(f'Our team needs meeting transcription using a Whisper AI model API. Task {i}.' for i in range(20))
    out=judge(text)
    assert len(out['evidence_contexts'])==8
    assert out['evidence_context_summary']['eligible_window_count']>8
    assert out['evidence_context_summary']['maximum_stored']==8
    assert out['data_quality']['original_characters']==len(text)


def test_theme_brief_excerpts_are_real_and_link_to_their_records():
    rows=[record(text='Our team needs AI to extract emails using an OCR model API. Currently we manually process customer emails every week.')]
    result=core.analyze({'direction':'企业办公自动化'},rows,LocalConfig().model_dump(),1)
    brief=result['clusters'][0]['brief']
    assert brief['current_process'] and brief['recurrence']
    for field in ('users','problems','current_process','gaps','recurrence','technical_basis'):
        for entry in brief[field]:
            assert entry['record_id']==rows[0]['id']
            assert rows[0]['content'][entry['start']:entry['end']]==entry['text']


def test_function_grouping_separates_categories_without_losing_members():
    rows=[record(i) for i in range(4)]
    judgments={r['id']:{'function':'语音处理' if i<2 else '图像识别'} for i,r in enumerate(rows)}
    distance=np.full((4,4),.1);np.fill_diagonal(distance,0)
    assert len(set(core.clustered_labels(distance,.65,rows,judgments,'flat')))==1
    groups=core.clustered_labels(distance,.65,rows,judgments,'function_then_text')
    assert len(groups)==4 and len(set(groups))==2
    assert groups[0]==groups[1] and groups[2]==groups[3] and groups[0]!=groups[2]
    with pytest.raises(ValueError):core.clustered_labels(distance,.65,rows,judgments,'unknown')


def test_judgment_cache_reuses_weights_changes_but_isolates_content_direction_and_threshold():
    local_cache.clear();row=record();cfg=LocalConfig().model_dump()
    with patch.object(core,'_judge',wraps=core._judge) as compute:
        first=core.judge(row,'企业办公自动化',cfg)
        first['reason']='mutated by caller'
        second=core.judge(row,'企业办公自动化',{**cfg,'coverage_weight':.8})
        assert compute.call_count==1 and second['reason']!='mutated by caller'
        core.judge(row,'医疗',cfg)
        core.judge({**row,'content':row['content']+' changed'},'企业办公自动化',cfg)
        core.judge(row,'企业办公自动化',{**cfg,'threshold':.9})
        assert compute.call_count==4
    assert local_cache.stats()['hits']==1


def test_cache_budget_eviction_and_large_values_cannot_exceed_bounds():
    local_cache.clear()
    with patch.object(local_cache,'MAX_BYTES',300),patch.object(local_cache,'MAX_ENTRIES',2):
        for i in range(6):local_cache.cached('test',i,lambda:{'text':'x'*80})
        assert local_cache.stats()['entries']<=2 and local_cache.stats()['bytes']<=300
        before=local_cache.stats()['entries']
        local_cache.cached('large',0,lambda:{'text':'x'*400})
        assert local_cache.stats()['entries']==before
    local_cache.clear()


def test_vector_cache_preserves_arrays_and_invalidates_changed_files(tmp_path):
    for name in (*local_embeddings.FILES,'manifest.json'):(tmp_path/name).write_text('fixture',encoding='utf8')
    local_cache.clear()
    with patch.dict('os.environ',{'OPPORTUNITY_E5_DIR':str(tmp_path)}),patch.object(local_embeddings,'_embed',return_value=(np.array([[1.,0.]]),{'fixture':True})) as compute:
        first,_=local_embeddings.embed(['text']);first[0,0]=0
        second,_=local_embeddings.embed(['text'])
        assert second[0,0]==1 and compute.call_count==1
        (tmp_path/'tokenizer.json').write_text('changed size',encoding='utf8')
        local_embeddings.embed(['text']);assert compute.call_count==2


def test_semantic_suggestions_never_change_official_candidates_or_clusters():
    rows=[record()];cfg=LocalConfig(direction_terms='contract',semantic_recall=True).model_dump()
    vectors=np.array([[1.,0.],[1.,0.],[1.,0.]])
    with patch.object(local_embeddings,'embed',return_value=(vectors,{'model_id':'test','revision':'test'})):
        result=core.analyze({'direction':'企业办公自动化'},rows,cfg,1)
    assert result['semantic_recall']['items'][0]['record_id']==rows[0]['id']
    assert result['candidate_count']==0 and result['clusters']==[]
    assert result['judgments'][rows[0]['id']]['opportunity']==0


def test_recall_ignores_excluded_technical_incidents_and_disabled_mode():
    rows=[record(text='Our team needs AI model API access for meeting reports. HTTP 503 is returned.')]
    judgments={rows[0]['id']:judge(rows[0]['content'])}
    with patch.object(local_embeddings,'embed',side_effect=AssertionError('should not embed')):
        assert local_recall.suggestions(rows,judgments,'办公',{})['status']=='disabled'
        assert local_recall.suggestions(rows,judgments,'办公',{'semantic_recall':True})['status']=='no_eligible_records'


def test_warm_cache_and_cold_cache_have_identical_analysis_outputs():
    rows=[record(i) for i in range(1,4)];cfg=LocalConfig(cluster_mode='function_then_text').model_dump()
    local_cache.clear()
    cold=core.analyze({'direction':'企业办公自动化'},rows,cfg,1)
    warm=core.analyze({'direction':'企业办公自动化'},deepcopy(rows),cfg,1)
    assert cold==warm and local_cache.stats()['hits']>=3
