"""Versioned program-analysis runs, evidence exports and planning revisions."""
import hashlib
import json
import threading
import time
import os
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

import local_analysis
import local_preprocessing
import local_comparison
import local_planning
import local_embeddings
import evidence_scoring
import context_rules
import local_value
import local_business
import local_cache
import local_recall
import local_submission
import collection_screening
import analysis_engine

RUN_LOCK = threading.Lock()


class LocalConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    threshold: float = Field(default=.7, ge=0, le=1, allow_inf_nan=False)
    distance_threshold: float = Field(default=.65, ge=.05, le=1.5, allow_inf_nan=False)
    dimensions: int = Field(default=32, ge=2, le=128)
    coverage_weight: float = Field(default=.6, ge=0, le=1, allow_inf_nan=False)
    scale_weight: float = Field(default=.4, ge=0, le=1, allow_inf_nan=False)
    direction_terms: str = Field(default='', max_length=2000)
    vector_method: Literal['lsa','tfidf','e5'] = 'lsa'
    cluster_mode: Literal['flat','function_then_text'] = 'flat'
    cache_enabled: bool = True
    semantic_recall: bool = False
    semantic_recall_threshold: float = Field(default=.85,ge=.5,le=1,allow_inf_nan=False)
    semantic_distance_threshold: float = Field(default=.15,ge=.01,le=.8,allow_inf_nan=False)
    score_method: Literal['evidence_strength','completeness'] = 'evidence_strength'

    @model_validator(mode='after')
    def weights(self):
        if self.coverage_weight + self.scale_weight <= 0:
            raise ValueError('两个评分权重不能同时为0')
        return self


def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS local_runs (
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
        created_at TEXT NOT NULL, status TEXT NOT NULL, config TEXT NOT NULL,
        result TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '')''')
    db.execute("UPDATE local_runs SET status='failed',error='服务重启导致中断，请创建新的分析记录' WHERE status IN ('queued','running')")
    db.execute('''CREATE TABLE IF NOT EXISTS local_plans (
        id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES local_runs(id),cluster_id TEXT NOT NULL,
        created_at TEXT NOT NULL,author TEXT NOT NULL,plan TEXT NOT NULL)''')


def install(app, connect, get_records, require_usable_batch, root, sources, csv_download):
    def read_run(batch_id, run_id):
        get_records(batch_id)
        with connect() as db:
            row = db.execute('SELECT * FROM local_runs WHERE batch_id=? AND id=?', (batch_id, run_id)).fetchone()
        if not row:
            raise HTTPException(404, '本批次不存在该分析记录')
        item = dict(row)
        item['config'], item['result'] = json.loads(item['config']), json.loads(item['result'])
        return item

    def finished(batch_id, run_id):
        require_usable_batch(batch_id)
        row = read_run(batch_id, run_id)
        if row['status'] != 'complete':
            raise HTTPException(409, '分析记录尚未完成')
        return row

    def worker(run_id, batch, records, config, source_count):
        try:
            with connect() as db:
                db.execute("UPDATE local_runs SET status='running' WHERE id=?", (run_id,))
            wall_start,cpu_start=time.perf_counter(),time.thread_time()
            cache_start=local_cache.stats()
            result = local_analysis.analyze(batch, records, config, source_count)
            result['source_code_sha256'] = hashlib.sha256(Path(local_analysis.__file__).read_bytes()).hexdigest()
            result['source_hashes'] = {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                       for module in (local_analysis, local_preprocessing, local_comparison, local_planning, local_embeddings, evidence_scoring, context_rules, local_value, local_business, local_cache, local_recall, local_submission, collection_screening, analysis_engine)}
            # Retain the exact inputs used by this run, not a future mutable database view.
            result['input_records'] = records
            result['proposal_drafts']=local_planning.initial_drafts(result)
            characters=sum(len(row['content']) for row in records)
            content_bytes=sum(len(row['content'].encode('utf8')) for row in records)
            result['execution_metrics']={
                'measurement_version':'local-worker-timing-v1',
                'wall_seconds':round(time.perf_counter()-wall_start,6),
                'cache':{**local_cache.stats(),'run_hits':local_cache.stats()['hits']-cache_start['hits'],
                         'run_misses':local_cache.stats()['misses']-cache_start['misses']},
                'worker_thread_cpu_seconds':round(time.thread_time()-cpu_start,6),
                'input_characters':characters,'input_content_utf8_bytes':content_bytes,
                'environment':{'system':platform.system(),'architecture':platform.machine(),
                               'logical_cpu_count':os.cpu_count()},
                'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'note':'测量本地分析、源码哈希与策划初稿阶段；不含采集、排队、结果序列化/写库、网络传输与页面渲染。CPU仅当前工作线程，不含其他线程或原生并行线程；逻辑CPU数不是分配核数。字符及UTF8字节只计输入content，不是内存峰值或数据库大小。耗时不可用于证明业务效果或零运行成本。'}
            with connect() as db:
                db.execute("UPDATE local_runs SET status='complete',result=? WHERE id=?",
                           (json.dumps(result, ensure_ascii=False, allow_nan=False), run_id))
        except Exception as error:
            with connect() as db:
                db.execute("UPDATE local_runs SET status='failed',error=? WHERE id=?", (str(error), run_id))
        finally:
            RUN_LOCK.release()

    @app.get('/local')
    def page():
        return FileResponse(root / 'local.html')

    @app.get('/local-ui.js')
    def javascript():
        return FileResponse(root / 'local-ui.js', media_type='application/javascript')

    @app.get('/api/batches/{batch_id}/local-runs')
    def history(batch_id: str):
        get_records(batch_id)
        with connect() as db:
            return [dict(r) for r in db.execute('SELECT id,batch_id,created_at,status,config,error FROM local_runs WHERE batch_id=? ORDER BY created_at DESC', (batch_id,))]

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}')
    def detail(batch_id: str, run_id: str):
        return read_run(batch_id, run_id)

    @app.post('/api/batches/{batch_id}/local-runs', status_code=202)
    def start(batch_id: str, body: LocalConfig, request: Request, background: BackgroundTasks):
        user = getattr(request.state, 'user', None)
        if not user or user.get('role') not in ('admin', 'researcher'):
            raise HTTPException(403, '研究员或管理员才能启动本地分析')
        require_usable_batch(batch_id)
        batch, records = get_records(batch_id)
        if (body.vector_method=='e5' or body.semantic_recall) and not local_embeddings.available():
            raise HTTPException(409,'本地E5模型未准备；请先运行setup_semantic_model.py，不会自动下载或换用其他算法')
        if batch['status'] != 'collected' or not records:
            raise HTTPException(409, '请先完成采集；部分失败批次应先复制完整成功来源')
        try:
            local_analysis.validate_input_size(records)
        except ValueError as error:
            raise HTTPException(413, str(error)) from error
        with connect() as db:
            row = db.execute('SELECT sources FROM batch_options WHERE batch_id=?', (batch_id,)).fetchone()
        selected = json.loads(row[0]) if row else []
        source_count = len({sources.NAMES.get(k, k) for k in selected}) or len({r['source'] for r in records})
        if not RUN_LOCK.acquire(blocking=False):
            raise HTTPException(409, '已有本地分析任务运行，请完成后再试')
        try:
            run_id = 'L'+uuid.uuid4().hex[:16].upper()
            config = body.model_dump()
            with connect() as db:
                db.execute('INSERT INTO local_runs(id,batch_id,created_at,status,config) VALUES (?,?,?,?,?)',
                           (run_id, batch_id, datetime.now(timezone.utc).isoformat(), 'queued', json.dumps(config)))
            background.add_task(worker, run_id, batch, records, config, source_count)
        except Exception:
            RUN_LOCK.release()
            raise
        return {'id': run_id, 'batch_id': batch_id, 'status': 'queued'}

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}/evidence.json')
    def evidence(batch_id: str, run_id: str):
        return finished(batch_id, run_id)

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}/compare/{other_id}')
    def compare(batch_id: str, run_id: str, other_id: str):
        left=finished(batch_id,run_id)['result']
        right=finished(batch_id,other_id)['result']
        return {'left_run_id':run_id,'right_run_id':other_id, **local_comparison.compare(left,right)}

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}/submission-check.json')
    def submission_check(batch_id: str,run_id: str):
        saved=finished(batch_id,run_id)
        return {'batch_id':batch_id,'run_id':run_id,**local_submission.check(saved['result'])}

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}/result{number}.csv')
    def export(batch_id: str, run_id: str, number: int):
        result = finished(batch_id, run_id)['result']
        if number == 1:
            header = ['采集批次号','记录编号','来源网站名称','来源链接','内容','发布时间','星标数','热度指标（原平台名称与数值）','更新时间','采集时间']
            rows = [[batch_id,r['id'],r['source'],r['url'],r['content'],r['published_at'],r['stars'],
                     json.dumps(r.get('metadata',{}).get('heat',{}),ensure_ascii=False),r.get('updated_at'),r.get('collected_at')]
                    for r in result['input_records']]
        elif number == 2:
            header = ['采集批次号','记录编号','是否构成机会','机会置信度','功能类别','所属行业']
            rows = [[batch_id,rid,j['opportunity'],j['confidence'],j['function'],j['industry']] for rid,j in result['judgments'].items()]
        elif number == 3:
            header = ['采集批次号','主题簇编号','主题簇名称','功能类别','所属行业','簇内机会记录数','来源网站覆盖','簇内机会记录编号']
            rows = [[batch_id,c['id'],c['name'],c['function'],c['industry'],c['count'],'；'.join(c['sources']),'；'.join(c['records'])] for c in result['clusters']]
        elif number == 4:
            header = ['采集批次号','主题簇编号','主题簇名称','功能类别','所属行业','机会价值分','优先级']
            rows = [[batch_id,c['id'],c['name'],c['function'],c['industry'],c['score'],c['priority']] for c in result['clusters']]
        else:
            raise HTTPException(404, '结果编号必须是1至4')
        return csv_download(header, rows, f'result{number}.csv')

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}/proposal/{cluster_id}.md')
    def proposal(batch_id: str, run_id: str, cluster_id: str):
        result = finished(batch_id, run_id)['result']
        cluster = next((c for c in result['clusters'] if c['id'] == cluster_id), None)
        if cluster is None:
            raise HTTPException(404, '主题不存在')
        saved=read_plan(run_id,cluster_id,result)
        text=local_planning.render(batch_id,run_id,cluster,result,saved['plan'],saved.get('id'),saved.get('origin'),saved.get('generator_version'))
        return Response(text, media_type='text/markdown', headers={'Content-Disposition':'attachment; filename="proposal.md"'})

    def read_plan(run_id,cluster_id,result):
        with connect() as db:
            row=db.execute('SELECT * FROM local_plans WHERE run_id=? AND cluster_id=? ORDER BY created_at DESC,id DESC LIMIT 1',
                           (run_id,cluster_id)).fetchone()
        if row:
            item=dict(row);item['plan']=json.loads(item['plan']);item['origin']='saved_revision'
            item['generator_version']=result.get('proposal_drafts',{}).get(cluster_id,{}).get('generator_version')
            return item
        draft=result.get('proposal_drafts',{}).get(cluster_id)
        if draft:return {**draft,'id':None}
        return {'plan':local_planning.Plan().model_dump(),'id':None,'origin':'legacy_blank'}

    def require_cluster(batch_id,run_id,cluster_id):
        result=finished(batch_id,run_id)['result']
        if not any(c['id']==cluster_id for c in result['clusters']):
            raise HTTPException(404,'主题不存在')
        return result

    @app.get('/api/batches/{batch_id}/local-runs/{run_id}/plans/{cluster_id}')
    def plan(batch_id: str,run_id: str,cluster_id: str):
        result=require_cluster(batch_id,run_id,cluster_id)
        return read_plan(run_id,cluster_id,result)

    @app.post('/api/batches/{batch_id}/local-runs/{run_id}/plans/{cluster_id}',status_code=201)
    def save_plan(batch_id: str,run_id: str,cluster_id: str,body:local_planning.Plan,request:Request):
        user=getattr(request.state,'user',None)
        if not user or user.get('role') not in ('admin','researcher','decision'):
            raise HTTPException(403,'当前角色不可编辑策划案')
        require_cluster(batch_id,run_id,cluster_id)
        plan_id='P'+uuid.uuid4().hex[:16].upper()
        with connect() as db:
            db.execute('INSERT INTO local_plans VALUES (?,?,?,?,?,?)',
                       (plan_id,run_id,cluster_id,datetime.now(timezone.utc).isoformat(),user['username'],json.dumps(body.model_dump(),ensure_ascii=False)))
        return {'id':plan_id,'saved':True,'note':'保存为新的策划修订，未改变分析结果或原文证据'}
