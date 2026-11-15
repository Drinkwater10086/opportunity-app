"""Model loading checks are optional; regular tests remain network-free."""
from unittest.mock import patch
import numpy as np
import pytest

import local_embeddings as embedding
import local_analysis as core
from local_routes import LocalConfig


class FakeEncoding:
    def __init__(self,text):self.offsets=[(i,i+1) for i in range(len(text))]


class FakeTokenizer:
    def encode(self,text,add_special_tokens=False):return FakeEncoding(text)


def test_token_chunking_covers_all_unicode_without_silent_truncation():
    text='会议纪要與résumé🙂 '*130
    parts=list(embedding.token_chunks(text,FakeTokenizer()))
    assert len(parts)>1
    covered=set()
    for p in parts:
        covered.update(range(p['token_start'],p['token_end']))
        assert text[p['start']:p['end']]==p['text']
        assert p['token_end']-p['token_start']<=480
    assert len(covered)==len(text)


def test_missing_model_does_not_download_or_fallback(tmp_path):
    with patch.dict('os.environ',{'OPPORTUNITY_E5_DIR':str(tmp_path)}),patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')):
        with pytest.raises(ValueError,match='未准备|尚未准备'):embedding.embed(['text'])


def test_engine_uses_chosen_embeddings_and_preserves_baseline():
    rows=[{'id':str(i),'source':'GitHub','title':'Meeting transcription',
           'content':f'Our team needs AI meeting transcription using Whisper model API. variant {i}'} for i in range(4)]
    vectors=np.array([[1.,0],[1.,0],[0,1.],[0,1.]])
    with patch.object(embedding,'embed',return_value=(vectors,{'test_only':True})) as call:
        out=core.analyze({'direction':'企业办公自动化'},rows,LocalConfig(vector_method='e5').model_dump(),1)
    assert call.call_count==1
    assert len(out['clusters'])==2
    assert out['evaluation']['structure_valid']
    assert out['effective_distance_threshold']==.15
    assert 'baseline_in_primary_space' in out['evaluation']
    assert out['embedding_metadata']['test_only']
    assert len(out['evaluation']['semantic_threshold_grid'])==5


def test_large_cluster_warning_is_not_hidden_by_numeric_silhouette():
    distances=np.ones((10,10));np.fill_diagonal(distances,0)
    report=core.diagnostic(distances,[0]*9+[1])
    assert report['silhouette'] is not None
    assert any('80%' in warning for warning in report['warnings'])


@pytest.mark.skipif(not embedding.available(),reason='optional local model not downloaded')
def test_real_model_is_offline_finite_and_reproducible():
    texts=['会议纪要需要提取待办事项。','Meeting notes should extract action items.']
    with patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')):
        first,meta=embedding.embed(texts)
        second,_=embedding.embed(texts)
    assert first.shape==(2,384) and np.all(np.isfinite(first))
    assert np.allclose(np.linalg.norm(first,axis=1),1)
    assert np.allclose(first,second)
    assert meta['revision']==embedding.REVISION and not meta['truncated']
    assert meta['prefix']=='query: '
