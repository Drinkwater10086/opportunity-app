from unittest.mock import patch
import app
from test_pipeline import client,source_fixture


def test_failed_source_does_not_consume_ids_or_dedup_future_sources(client):
    first=source_fixture('github','test',1,365)[0][0]
    malformed={**first,'title':'malformed','url':'https://github.com/example/other','raw_text':None}
    later={**first,'url':'https://stackoverflow.com/questions/123/test'}
    def fetch(source,*args,**kwargs):
        return ([first,malformed] if source=='github' else [later]),{'complete':True}
    with patch.object(app.sources,'fetch',side_effect=fetch):
        r=client.post('/api/batches',json={'direction':'测试','query':'test','sources':['github','stackoverflow']})
    data=client.get('/api/batches/'+r.json()['id']).json()
    assert data['batch']['status']=='partial'
    assert len(data['records'])==1
    assert data['records'][0]['id']=='S00001' and data['records'][0]['source']=='Stack Overflow'


def test_database_error_rolls_back_source_before_dedup_state_is_committed(client):
    first=source_fixture('github','test',1,365)[0][0]
    rejected={**first,'title':'trigger-error','url':'https://github.com/example/other'}
    later={**first,'url':'https://stackoverflow.com/questions/123/test'}
    with app.connect() as db:
        db.execute("CREATE TRIGGER fail_synthetic BEFORE INSERT ON records WHEN NEW.title='trigger-error' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    def fetch(source,*args,**kwargs):
        return ([first,rejected] if source=='github' else [later]),{'complete':True}
    with patch.object(app.sources,'fetch',side_effect=fetch):
        r=client.post('/api/batches',json={'direction':'测试','query':'test','sources':['github','stackoverflow']})
    data=client.get('/api/batches/'+r.json()['id']).json()
    assert data['batch']['status']=='partial' and len(data['records'])==1
    assert data['records'][0]['id']=='S00001' and data['records'][0]['source']=='Stack Overflow'


def test_unexpected_source_exception_does_not_leave_batch_running(client):
    def fetch(source,query,limit,days,window_end=None):
        if source=='github':
            raise RuntimeError('synthetic provider failure')
        return source_fixture(source,query,limit,days)
    with patch.object(app.sources,'fetch',side_effect=fetch):
        r=client.post('/api/batches',json={'direction':'测试','query':'test','sources':['github','stackoverflow']})
    data=client.get('/api/batches/'+r.json()['id']).json()
    assert data['batch']['status']=='partial' and len(data['records'])==1
    failed=next(s for s in data['sources'] if s['source']=='github')
    assert failed['status']=='failed' and 'RuntimeError' in failed['metadata']
