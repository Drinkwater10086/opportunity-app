"""Synthetic replay integrity tests; not collected research observations."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest
import local_analysis
from local_routes import LocalConfig
import replay_local_analysis as tool


@pytest.fixture
def snapshot():
    rows=[{'id':'S00001','title':'Meeting transcripts','content':'Our team needs AI meeting transcription using a Whisper model API.','source':'test'}]
    result=local_analysis.analyze({'direction':'企业办公自动化'},rows,LocalConfig().model_dump(),2)
    result.update(input_records=rows,source_hashes=tool.code_hashes())
    return {'result':result}


def test_identical_replay_without_network(snapshot):
    with patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')):
        report=tool.replay(snapshot)
    assert report['same_outputs'] and report['input_verified']
    assert not report['changed_code_modules']
    assert not report['different_fields']


def test_input_tampering_and_wrong_direction_rejected(snapshot):
    changed=deepcopy(snapshot);changed['result']['input_records'][0]['content']+=' extra'
    with pytest.raises(ValueError,match='哈希'):tool.replay(changed)
    with pytest.raises(ValueError,match='方向不一致'):tool.replay(snapshot,direction='other')
    old=deepcopy(snapshot);del old['result']['direction']
    with pytest.raises(ValueError,match='缺少研究方向'):tool.replay(old)
    assert tool.replay(old,direction='企业办公自动化')['same_outputs']


def test_changed_code_requires_explicit_comparison(snapshot):
    snapshot['result']['source_hashes']['context_rules']='changed'
    with pytest.raises(ValueError,match='代码或运行库'):tool.replay(snapshot)
    report=tool.replay(snapshot,allow_code_change=True)
    assert report['changed_code_modules']==['context_rules']
    assert report['same_outputs']


def test_different_saved_decision_is_detected(snapshot):
    snapshot['result']['judgments']['S00001']['confidence']=0
    report=tool.replay(snapshot)
    assert not report['same_outputs']
    assert 'judgments' in report['different_fields']


def test_cli_writes_only_summary_and_preserves_input(snapshot,tmp_path):
    path=tmp_path/'evidence.json';path.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf8')
    before=path.read_bytes();out=tmp_path/'summary.json'
    assert tool.main([str(path),'--output',str(out)])==0
    report=json.loads(out.read_text(encoding='utf8'))
    assert report['same_outputs']
    assert 'input_records' not in report
    assert path.read_bytes()==before
    with pytest.raises(SystemExit) as exc:tool.main([str(path),'--output',str(path)])
    assert exc.value.code==2 and path.read_bytes()==before
