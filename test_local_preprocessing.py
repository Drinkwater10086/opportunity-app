"""Adversarial fixtures are synthetic, never competition observations."""
import numpy as np
import local_preprocessing as prep
import local_analysis as core
from local_routes import LocalConfig


def item(i, content):
    return {'id':f'S{i:05d}','title':'Meeting workflow','content':content,'source':'GitHub'}


def judge(text):
    return core.judge(item(1,text),'企业办公自动化',LocalConfig().model_dump())


def test_cross_paragraph_evidence_cannot_be_combined():
    text='Our team needs better meeting notes and manual reports.\n\nA separate benchmark discusses a Whisper AI model API.'
    assert judge(text)['opportunity']==0
    valid=judge('Our team needs better meeting notes. Whisper AI transcription model API could support this workflow.')
    assert valid['opportunity']==1
    for span in valid['evidence_spans'].values():
        if span:assert valid['selected_context']['start']<=span['start']<span['end']<=valid['selected_context']['end']


def test_new_collection_cleaning_preserves_paragraphs_and_is_idempotent():
    from app import clean
    text='Ａ team   needs help.\r\n\r\n```python\nprint(1)\n```\n\nOther https://example.com/path'
    cleaned=clean(text)
    assert '\n\n' in cleaned and '```python\n' in cleaned
    assert 'https://' not in cleaned and 'A team needs help.' in cleaned
    assert clean(cleaned)==cleaned


def test_code_and_quotes_remain_traceable_but_not_demand():
    for text in ['```python\nOur team needs AI meeting transcription with Whisper model API.\n```',
                 '> Our team needs AI meeting transcription with Whisper model API.\n']:
        result=judge(text)
        assert result['opportunity']==0
        assert result['preprocessing']['excluded_spans']
        view=prep.structure(text)['text']
        assert len(view)==len(text)
    text='Quoted history:\n> No need for AI.\n\nOur team needs meeting transcription with a Whisper AI model API.'
    result=judge(text)
    assert result['opportunity']==1
    for span in result['evidence_spans'].values():
        if span:assert text[span['start']:span['end']]==span['text']


def test_negation_only_applies_to_selected_context():
    text='An old email system runs without AI.\n\nOur team needs meeting transcription using a Whisper AI model API.'
    assert judge(text)['opportunity']==1
    assert judge('Our team needs meeting transcription without AI using a manual workflow API.')['opportunity']==0


def test_duplicates_are_not_deleted_and_critical_differences_preserved():
    rows=[item(1,'Our team needs meeting transcription API.'),item(2,'Our team needs meeting transcription API.'),
          item(3,'Our team does not need meeting transcription API.'),item(4,'Our team needs 20 meeting transcription API.')]
    distances=np.zeros((4,4))
    report=prep.duplicate_groups(rows,distances)
    assert report['duplicate_count']==1
    assert report['groups'][0]['records']==['S00001','S00002']
    assert len(rows)==4


def test_duplicate_chains_are_not_transitively_merged():
    rows=[item(i,'The same meeting transcription request.') for i in range(1,4)]
    distances=np.array([[0,.02,.08],[.02,0,.02],[.08,.02,0]])
    assert prep.duplicate_groups(rows,distances)['groups'][0]['records']==['S00001','S00002']


def test_duplicate_adjustment_preserves_cluster_members_and_raw_count():
    rows=[item(i,'Our team needs meeting transcription using a Whisper AI model API.') for i in range(1,4)]
    result=core.analyze({'direction':'企业办公自动化'},rows,LocalConfig().model_dump(),1)
    assert result['candidate_count']==3
    assert result['duplicate_diagnostics']['duplicate_count']==2
    assert result['clusters'][0]['count']==3
    assert result['clusters'][0]['unique_evidence_count']==1
    assert result['clusters'][0]['score']==result['clusters'][0]['score_before_duplicate_adjustment']
    assert 'duplicate_adjusted_score' in result['clusters'][0]
    assert result['evaluation']['structure_valid']
