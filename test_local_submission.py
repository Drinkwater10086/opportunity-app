from copy import deepcopy
import pytest
import local_analysis
import local_submission
from local_routes import LocalConfig


def result():
    records=[{'id':'S1','title':'Meeting','source':'GitHub','url':'https://github.com/example/1',
              'content':'Our team needs meeting transcription using a Whisper AI model API.'}]
    data=local_analysis.analyze({'direction':'企业办公自动化'},records,LocalConfig().model_dump(),1)
    return {**data,'input_records':records}


def test_four_tables_have_matching_rows_and_members_without_mutation():
    data=result();before=deepcopy(data);check=local_submission.check(data)
    assert check['passed'] and data==before
    assert check['rows']=={'result1.csv':1,'result2.csv':1,'result3.csv':1,'result4.csv':1}


@pytest.mark.parametrize('change',[
    lambda data:data['judgments'].clear(),
    lambda data:data['judgments']['S1'].update(confidence=1.1),
    lambda data:data['judgments']['S1'].update(function='not a valid label'),
    lambda data:data['clusters'][0].update(records=['unknown']),
    lambda data:data['clusters'][0].update(sources=['unknown']),
    lambda data:data['clusters'][0].update(score=float('nan')),
    lambda data:data['clusters'][0].update(priority=2),
])
def test_inconsistent_submission_fields_are_reported(change):
    data=result();change(data)
    assert not local_submission.check(data)['passed']
