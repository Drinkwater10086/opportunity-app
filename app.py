"""Local competition prototype: real acquisition, batch isolation, evidence export."""
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import csv
import io
import json
import re
import sqlite3
import threading
import unicodedata
import uuid
import os
import hashlib
import time
from typing import Literal
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
import sources
import source_policy
import analysis_engine as engine
import auth
import automatic_evaluation
import local_routes

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LOCK = threading.Lock()
ANALYSIS_LOCK = threading.Lock()
STABILITY_LOCK = threading.Lock()
STABILITY_JOBS = {}
MODEL_KEY = ''
BIGMODEL_KEY = ''
MODEL_PROVIDER = 'deepseek'
ANALYSIS_STOPS = {}
ROUTING_LOCK = threading.Lock()
PROVIDER_COOLDOWNS = {}
RETRYABLE_PROVIDER_STATUS = (429, 500, 502, 503, 504)


@contextmanager
def connect():
    DATA.mkdir(exist_ok=True, parents=True)
    db = sqlite3.connect(DATA / 'app.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY, direction TEXT NOT NULL, query TEXT NOT NULL,
            limit_count INTEGER NOT NULL, days INTEGER NOT NULL,
            created_at TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS records (
            batch_id TEXT NOT NULL REFERENCES batches(id), id TEXT NOT NULL,
            source TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
            raw_text TEXT NOT NULL, content TEXT NOT NULL, published_at TEXT,
            updated_at TEXT, stars INTEGER, collected_at TEXT NOT NULL,
            PRIMARY KEY(batch_id,id), UNIQUE(batch_id,url)
        );
        CREATE TABLE IF NOT EXISTS batch_options(batch_id TEXT PRIMARY KEY REFERENCES batches(id),sources TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_runs(batch_id TEXT NOT NULL REFERENCES batches(id),source TEXT NOT NULL,status TEXT NOT NULL,metadata TEXT NOT NULL,PRIMARY KEY(batch_id,source));
        CREATE TABLE IF NOT EXISTS record_meta(batch_id TEXT NOT NULL,record_id TEXT NOT NULL,metadata TEXT NOT NULL,PRIMARY KEY(batch_id,record_id),FOREIGN KEY(batch_id,record_id) REFERENCES records(batch_id,id));
        CREATE TABLE IF NOT EXISTS analyses(batch_id TEXT PRIMARY KEY REFERENCES batches(id),status TEXT NOT NULL,config TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',clusters TEXT NOT NULL DEFAULT '[]',metrics TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS judgments(batch_id TEXT NOT NULL,record_id TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(batch_id,record_id),FOREIGN KEY(batch_id,record_id) REFERENCES records(batch_id,id));
        CREATE TABLE IF NOT EXISTS model_calls(id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES batches(id),stage TEXT NOT NULL,created_at TEXT NOT NULL,prompt TEXT NOT NULL,response TEXT NOT NULL,usage TEXT NOT NULL,model TEXT NOT NULL,estimated_cost REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(batch_id TEXT NOT NULL,record_id TEXT NOT NULL,reviewer TEXT NOT NULL,label INTEGER NOT NULL,reason TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(batch_id,record_id,reviewer),FOREIGN KEY(batch_id,record_id) REFERENCES records(batch_id,id));
        CREATE TABLE IF NOT EXISTS pair_reviews(batch_id TEXT NOT NULL REFERENCES batches(id),left_id TEXT NOT NULL,right_id TEXT NOT NULL,reviewer TEXT NOT NULL,same_topic INTEGER NOT NULL,PRIMARY KEY(batch_id,left_id,right_id,reviewer));
        ''')
        auth.init(db)
        local_routes.init(db)
        db.execute("UPDATE batches SET status='failed',error='上次运行中断，请新建批次重试' WHERE status IN ('queued','running')")
        db.execute("UPDATE analyses SET status='failed',error='运行中断；已完成的判别可复用，点击继续分析' WHERE status IN ('queued','running')")


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title='AI 机会研究台', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
auth.install(app, connect)


@app.middleware('http')
async def local_writes(request: Request, call_next):
    if request.method == 'POST':
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return Response('不允许跨站提交', status_code=403)
    return await call_next(request)


class BatchInput(BaseModel):
    direction: str = Field(min_length=2, max_length=120)
    query: str = Field(min_length=2, max_length=1300)
    limit: int = Field(default=100, ge=1, le=500)
    days: int = Field(default=365, ge=1, le=730)
    sources: list[Literal['github', 'github_issues', 'stackoverflow', 'hackernews', 'superuser', 'workplace', 'n8n', 'make', 'nodered', 'v2ex', 'arxiv']] = Field(default=['github'], min_length=1, max_length=11)


def clean(text):
    text = unicodedata.normalize('NFKC', text)
    return re.sub(r'\s+', ' ', re.sub(r'https?://\S+', '', text)).strip()


def collect(batch_id):
    with LOCK:
        with connect() as db:
            batch = dict(db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone())
            option = db.execute('SELECT sources FROM batch_options WHERE batch_id=?', (batch_id,)).fetchone()
            selected = json.loads(option['sources']) if option else ['github']
            db.execute("UPDATE batches SET status='running' WHERE id=?", (batch_id,))
        seen, urls = set(), set()
        count, successful = 0, 0
        errors = []
        for source in selected:
            window_end = None
            try:
                window_end = datetime.fromisoformat(batch['created_at']).replace(microsecond=0)
                items, metadata = sources.fetch(source, batch['query'], batch['limit_count'], batch['days'], window_end=window_end)
                rows, meta_rows = [], []
                pending_seen, pending_urls = set(), set()
                pending_count = count
                for item in items:
                    content = clean(item['title'] + '\n' + item['raw_text'])
                    key = content.casefold()
                    if key in seen or key in pending_seen or item['url'] in urls or item['url'] in pending_urls:
                        continue
                    pending_seen.add(key)
                    pending_urls.add(item['url'])
                    pending_count += 1
                    rid = f'S{pending_count:05d}'
                    rows.append((batch_id, rid, sources.NAMES[source], item['url'], item['title'],
                                 item['raw_text'], content, item['published_at'], item['updated_at'],
                                 item['stars'], datetime.now(timezone.utc).isoformat()))
                    meta_rows.append((batch_id, rid, json.dumps({'heat': item['heat'], 'license': item['license'],
                        'provenance': item.get('provenance', {}),
                        'reliability': item.get('reliability', {}),
                        'privacy': {'method': 'rule-redaction-v3', 'complete_personal_data_detection': False,
                                    'note': '规则移除常见联系方式与凭据；姓名、签名、住址等自由文本仍可能残留，不能视为完整匿名化'},
                        'transformations': 'HTML转文本（如适用）、明显联系方式脱敏、Unicode及空白规范化、清洗文本去URL'}, ensure_ascii=False)))
                metadata['kept_count'] = len(rows)
                metadata['deduplicated_count'] = len(items)-len(rows)
                with connect() as db:
                    db.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
                    db.executemany('INSERT INTO record_meta VALUES (?,?,?)', meta_rows)
                    db.execute('INSERT INTO source_runs VALUES (?,?,?,?)', (batch_id, source, 'success' if metadata.get('complete', True) else 'partial', json.dumps(metadata, ensure_ascii=False)))
                seen.update(pending_seen)
                urls.update(pending_urls)
                count = pending_count
                if metadata.get('complete', True):
                    successful += 1
                else:
                    errors.append(f"{sources.NAMES[source]}：{metadata.get('error', '分页未完成')}")
            except Exception as exc:
                # A source adapter failure must not strand the batch in "running".
                # Other exception types expose their class, not response bodies.
                message = sources.redact(str(exc))[:500] if isinstance(exc, ValueError) else f'{sources.NAMES[source]} 采集失败（{type(exc).__name__}）'
                errors.append(message)
                failure_meta = {'error': message}
                if window_end is not None and window_end.tzinfo is not None:
                    failure_meta.update(window_start=(window_end-timedelta(days=batch['days'])).isoformat(),
                                        window_end=window_end.isoformat())
                with connect() as db:
                    db.execute('INSERT OR REPLACE INTO source_runs VALUES (?,?,?,?)', (batch_id, source, 'failed', json.dumps(failure_meta, ensure_ascii=False)))
        with connect() as db:
            state = 'collected' if successful == len(selected) else ('partial' if successful or count else 'failed')
            db.execute('UPDATE batches SET status=?,error=? WHERE id=?', (state, '\n'.join(errors), batch_id))


@app.get('/')
def home():
    return FileResponse(ROOT / 'index.html')


@app.get('/ui.js')
def javascript():
    return FileResponse(ROOT / 'ui.js', media_type='text/javascript')


@app.get('/style.css')
def stylesheet():
    return FileResponse(ROOT / 'style.css', media_type='text/css')


@app.get('/api/batches')
def batches():
    with connect() as db:
        return [dict(row) for row in db.execute('''SELECT b.*, (SELECT COUNT(*) FROM records r
              WHERE r.batch_id=b.id) AS count FROM batches b ORDER BY created_at DESC''')]


@app.post('/api/batches', status_code=202)
def create_batch(body: BatchInput, background: BackgroundTasks):
    try:
        source_policy.require_allowed(body.sources)
        sources.queries(body.query)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not body.direction.strip() or not body.query.strip():
        raise HTTPException(422, '需求方向与检索词不能为空')
    batch_id = 'B' + uuid.uuid4().hex[:12].upper()
    with connect() as db:
        pending = db.execute("SELECT COUNT(*) FROM batches WHERE status IN ('queued','running')").fetchone()[0]
        if pending >= 3:
            raise HTTPException(429, '最多同时保留 3 个待执行批次，请等待完成')
        db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)',
                   (batch_id, body.direction.strip(), body.query.strip(), body.limit, body.days,
                    datetime.now(timezone.utc).isoformat(), 'queued', ''))
        db.execute('INSERT INTO batch_options VALUES (?,?)', (batch_id, json.dumps(list(dict.fromkeys(body.sources)))))
    background.add_task(collect, batch_id)
    return {'id': batch_id}


def get_records(batch_id):
    with connect() as db:
        batch = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
        if batch is None:
            raise HTTPException(404, '批次不存在')
        records = [dict(row) for row in db.execute('SELECT * FROM records WHERE batch_id=? ORDER BY id', (batch_id,))]
        metadata = {r['record_id']: json.loads(r['metadata']) for r in db.execute('SELECT * FROM record_meta WHERE batch_id=?', (batch_id,))}
        for r in records:
            r['metadata'] = metadata.get(r['id'], {'heat': {'星标数': r['stars']}})
    return dict(batch), records


@app.get('/api/batches/{batch_id}')
def detail(batch_id: str):
    batch, records = get_records(batch_id)
    with connect() as db:
        logs = [dict(r) for r in db.execute('SELECT * FROM source_runs WHERE batch_id=?', (batch_id,))]
    return {'batch': batch, 'records': records, 'sources': logs, 'analysis': analysis_state(batch_id),
            'source_policy_issues': batch_source_issues(batch_id)}


def batch_source_issues(batch_id):
    with connect() as db:
        row = db.execute('SELECT sources FROM batch_options WHERE batch_id=?', (batch_id,)).fetchone()
        selected = json.loads(row[0]) if row else []
        names = {r[0] for r in db.execute('SELECT DISTINCT source FROM records WHERE batch_id=?', (batch_id,))}
    selected += [k for k, v in source_policy.BLOCKED.items() if v['name'] in names]
    return source_policy.issues(selected)


def require_usable_batch(batch_id):
    issues = batch_source_issues(batch_id)
    if issues:
        raise HTTPException(409, '该批次含已停用来源，仅保留核查记录，不能用于新分析或正式结果导出：'+
                            '、'.join(i['name'] for i in issues))


def csv_safe(value):
    text = '' if value is None else str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


@app.get('/api/batches/{batch_id}/result1.csv')
def export(batch_id: str):
    batch, records = get_records(batch_id)
    require_usable_batch(batch_id)
    if batch['status'] not in ('collected', 'partial'):
        raise HTTPException(409, '采集成功后才可导出')
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['采集批次号', '记录编号', '来源网站名称', '来源链接', '内容', '发布时间', '热度指标（如浏览数、点赞数、讨论数等）'])
    for r in records:
        writer.writerow([csv_safe(v) for v in [batch_id, r['id'], r['source'], r['url'], r['content'], r['published_at'], json.dumps(r['metadata']['heat'], ensure_ascii=False)]])
    return Response(stream.getvalue().encode('utf-8-sig'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="result1.csv"'})


@app.get('/api/batches/{batch_id}/evidence.json')
def evidence(batch_id: str):
    data = detail(batch_id)
    with connect() as db:
        data['model_calls'] = [dict(r) for r in db.execute('SELECT * FROM model_calls WHERE batch_id=? ORDER BY id', (batch_id,))]
        data['reviews'] = [dict(r) for r in db.execute('SELECT * FROM reviews WHERE batch_id=?', (batch_id,))]
        data['pair_reviews'] = [dict(r) for r in db.execute('SELECT * FROM pair_reviews WHERE batch_id=?', (batch_id,))]
    return Response(json.dumps(data, ensure_ascii=False, indent=2),
                    media_type='application/json', headers={'Content-Disposition': 'attachment; filename="evidence.json"'})


class ModelConfig(BaseModel):
    provider: Literal['deepseek', 'bigmodel'] = 'deepseek'
    api_key: str = Field(min_length=10, max_length=300)


class AnalysisInput(BaseModel):
    verification_provider: Literal['none', 'deepseek', 'bigmodel'] = 'none'
    fallback_enabled: bool = False
    concurrency: int = Field(default=1, ge=1, le=32)
    threshold: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    coverage_weight: float = Field(default=0.6, gt=0, le=1, allow_inf_nan=False)
    scale_weight: float = Field(default=0.4, gt=0, le=1, allow_inf_nan=False)
    budget_yuan: float = Field(default=5, gt=0, le=100, allow_inf_nan=False)


class StabilityInput(BaseModel):
    provider: Literal['deepseek', 'bigmodel'] = 'deepseek'
    budget_yuan: float | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)


def model_key(provider=None):
    if (provider or MODEL_PROVIDER) == 'bigmodel':
        return BIGMODEL_KEY or os.environ.get('BIGMODEL_API_KEY', '')
    return MODEL_KEY or os.environ.get('DEEPSEEK_API_KEY', '')


@app.get('/api/config')
def config():
    return {'provider': MODEL_PROVIDER, 'providers': engine.PROVIDERS,
            'configured_providers': {p: bool(model_key(p)) for p in engine.PROVIDERS},
            'model': engine.PROVIDERS[MODEL_PROVIDER]['model'], 'key_configured': bool(model_key()),
            'prompt_version': engine.PROMPT_VERSION, 'functions': engine.FUNCTIONS, 'industries': engine.INDUSTRIES}


@app.post('/api/config')
def configure(body: ModelConfig):
    global MODEL_KEY, BIGMODEL_KEY, MODEL_PROVIDER
    if body.provider == 'bigmodel':
        BIGMODEL_KEY = body.api_key.strip()
    else:
        MODEL_KEY = body.api_key.strip()
    MODEL_PROVIDER = body.provider
    return {'key_configured': bool(model_key()), 'storage': '仅服务进程内存，重启失效'}


def analysis_state(batch_id):
    with connect() as db:
        row = db.execute('SELECT * FROM analyses WHERE batch_id=?', (batch_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for k in ('config', 'clusters', 'metrics'):
            result[k] = json.loads(result[k])
        result['judgments'] = {r['record_id']: json.loads(r['result']) for r in db.execute('SELECT * FROM judgments WHERE batch_id=?', (batch_id,))}
        calls = [dict(r) for r in db.execute('SELECT id,stage,usage,model,estimated_cost FROM model_calls WHERE batch_id=?', (batch_id,))]
        result['calls'] = calls
        confirmed = reserved = 0
        result['retry_after_seconds'] = 0
        for c in calls:
            usage = json.loads(c['usage'])
            known = valid_model_usage(usage)
            if known:
                confirmed += c['estimated_cost']
            else:
                reserved += c['estimated_cost']
            result['retry_after_seconds'] = max(result['retry_after_seconds'], max(0, int(usage.get('_retry_at', 0)-time.time()+0.999)))
        result['estimated_cost_yuan'] = round(confirmed, 6)
        result['unconfirmed_reserve_yuan'] = round(reserved, 6)
    if result['config'].get('fallback_enabled'):
        waits = [provider_cooldown(p) for p in result['config']['provider_pool']]
        result['retry_after_seconds'] = int(min(waits)+0.999) if waits else 0
    result['evaluation'] = evaluation(batch_id, result)
    return result


def valid_model_usage(usage):
    """Only non-negative JSON integers establish provider-reported usage."""
    return isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                                           for k in ('prompt_tokens', 'completion_tokens'))


@app.get('/api/batches/{batch_id}/automatic-evaluation.json')
def automatic_report(batch_id: str):
    require_usable_batch(batch_id)
    _, records = get_records(batch_id)
    state = analysis_state(batch_id)
    if not state or state['status'] != 'complete':
        raise HTTPException(409, '完成自动分析后才能评价最终聚类')
    positives = {k for k, v in state['judgments'].items() if v['opportunity']}
    with connect() as db:
        calls = db.execute("SELECT prompt,response FROM model_calls WHERE batch_id=? AND stage='cluster' ORDER BY id", (batch_id,)).fetchall()
    groups = {}
    for call in calls:
        try:
            prompt = json.loads(call['prompt'])
            if prompt['user'].get('repair'):
                continue
            output = engine.parse_reply(json.loads(call['response']))
            clusters = engine.validate_clusters(output, positives)
            groups.setdefault(call['prompt'], []).append(clusters)
        except (ValueError, KeyError, TypeError, IndexError):
            continue
    runs = max(groups.values(), key=len, default=[])
    report = automatic_evaluation.evaluate(json.dumps({
        'records': [{'id': r['id'], 'content': r['content']} for r in records],
        'clusters': state['clusters'], 'positive_ids': sorted(positives), 'valid_runs': runs,
    }, ensure_ascii=False, sort_keys=True))
    return {**report, 'batch_id': batch_id, 'analysis_config': state['config'],
            'screening': automatic_evaluation.screening_diagnostics(state['judgments'], state['config']['threshold']),
            'method_update_available': state['config'].get('prompt_version') not in
                (engine.PROMPT_VERSION, engine.PROVIDERS['bigmodel']['prompt_version'])}


def evaluation(batch_id, state):
    with connect() as db:
        rows = db.execute('SELECT * FROM reviews WHERE batch_id=?', (batch_id,)).fetchall()
        pairs = db.execute('SELECT * FROM pair_reviews WHERE batch_id=?', (batch_id,)).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r['record_id'], set()).add(r['label'])
    consensus = {rid: next(iter(labels)) for rid, labels in grouped.items() if len(labels) == 1 and rid in state['judgments']}
    tp = fp = fn = tn = 0
    for rid, label in consensus.items():
        predicted = state['judgments'][rid]['opportunity']
        tp += int(predicted == label == 1)
        tn += int(predicted == label == 0)
        fp += int(predicted == 1 and label == 0)
        fn += int(predicted == 0 and label == 1)
    n = len(consensus)
    membership = {rid: c['id'] for c in state['clusters'] for rid in c['records']}
    pair_labels = {}
    for r in pairs:
        pair_labels.setdefault((r['left_id'], r['right_id']), set()).add(r['same_topic'])
    usable = [(a, b, next(iter(labels))) for (a, b), labels in pair_labels.items()
              if len(labels) == 1 and a in membership and b in membership]
    return {'reviewed_records': n, 'disagreements': sum(len(v) > 1 for v in grouped.values()),
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'accuracy': (tp+tn)/n if n else None,
            'precision': tp/(tp+fp) if tp+fp else None,
            'recall': tp/(tp+fn) if tp+fn else None,
            'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
            'reviewed_pairs': len(usable),
            'pair_agreement': sum(int(membership[a] == membership[b]) == label for a,b,label in usable)/len(usable) if usable else None,
            'note': '仅计算人工已标注且无分歧的样本，非总体准确率；未经标注时不生成效果数字。'}


def analysis_config(batch_id):
    with connect() as db:
        return json.loads(db.execute('SELECT config FROM analyses WHERE batch_id=?', (batch_id,)).fetchone()[0])


def provider_cooldown(provider):
    # Also honor persisted cooldowns after process restart, across all batches.
    with connect() as db:
        rows = db.execute("SELECT usage,model FROM model_calls WHERE usage LIKE '%_retry_at%'").fetchall()
    until = 0
    for row in rows:
        usage = json.loads(row['usage'])
        owner = usage.get('_provider') or next((p for p,s in engine.PROVIDERS.items() if s['model']==row['model']), None)
        if owner == provider:
            until = max(until, usage.get('_retry_at', 0))
    with ROUTING_LOCK:
        return max(0, max(until, PROVIDER_COOLDOWNS.get(provider, 0))-time.time())


def request_analysis(batch_id, stage, prompt, max_tokens, key, budget, preferred_provider=None):
    cfg = analysis_config(batch_id)
    primary = cfg.get('provider', 'deepseek')
    pool = cfg.get('provider_pool', [primary]) if cfg.get('fallback_enabled') else [primary]
    if preferred_provider in pool:
        pool = [preferred_provider]+[p for p in pool if p != preferred_provider]
    last_error = None
    for provider in pool:
        if cfg.get('fallback_enabled') and provider_cooldown(provider) > 0:
            continue
        actual_key = key.get(provider, '') if isinstance(key, dict) else (key if provider==primary else model_key(provider))
        if not actual_key:
            continue
        try:
            return request_provider(batch_id, stage, prompt, max_tokens, actual_key, budget, provider)
        except engine.ProviderError as exc:
            if not cfg.get('fallback_enabled') or exc.status_code not in RETRYABLE_PROVIDER_STATUS:
                raise
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError('模型池暂无可用服务：服务冷却中或未配置密钥，已保存进度，请稍后继续')


def request_provider(batch_id, stage, prompt, max_tokens, key, budget, provider):
    stop = ANALYSIS_STOPS.get(batch_id)
    if stop and stop.is_set():
        raise ValueError('并发分析已暂停，已完成结果保留')
    spec = engine.PROVIDERS[provider]
    prompt_text = json.dumps({'system': engine.system_prompt(provider, prompt), 'user': prompt}, ensure_ascii=False)
    # Conservative byte-based reservation, high-period prices from 2026-11-07.
    # This is a local guard, not an authoritative provider billing cap.
    reserve = 0 if spec['free'] else ((len(prompt_text.encode('utf-8'))+1024)*2 + max_tokens*8)/1_000_000
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if stop and stop.is_set():
            raise ValueError('并发分析已暂停，已完成结果保留')
        spent = db.execute('SELECT COALESCE(SUM(estimated_cost),0) FROM model_calls WHERE batch_id=?', (batch_id,)).fetchone()[0]
        if spent + reserve > budget:
            raise ValueError('达到本批次预算保护阈值；已完成结果已保留，可提高预算后继续')
        cursor = db.execute('INSERT INTO model_calls(batch_id,stage,created_at,prompt,response,usage,model,estimated_cost) VALUES (?,?,?,?,?,?,?,?)',
                            (batch_id, stage, datetime.now(timezone.utc).isoformat(), prompt_text,
                             '请求已提交；尚未收到完整响应', '{}', spec['model'], reserve))
        call_id = cursor.lastrowid
    try:
        reply = (engine.call_model(key, prompt, max_tokens) if provider == 'deepseek'
                 else engine.call_model(key, prompt, max_tokens, provider=provider))
    except engine.ProviderError as exc:
        until = time.time()+exc.retry_seconds
        with ROUTING_LOCK:
            PROVIDER_COOLDOWNS[provider] = max(PROVIDER_COOLDOWNS.get(provider, 0), until)
        usage = {'_provider': provider, '_request_state': 'http_error', '_http_status': exc.status_code,
                 '_retry_at': until,
                 '_billing': '无token用量，保留预算预留；是否扣费须核对供应商账单'}
        with connect() as db:
            db.execute('UPDATE model_calls SET response=?,usage=? WHERE id=?',
                       (json.dumps({'error': str(exc), 'http_status': exc.status_code}, ensure_ascii=False), json.dumps(usage, ensure_ascii=False), call_id))
        raise
    except requests.RequestException as exc:
        with connect() as db:
            db.execute('UPDATE model_calls SET response=?,usage=? WHERE id=?',
                       (json.dumps({'error': type(exc).__name__}), json.dumps({'_provider':provider, '_request_state':'transport_error', '_retry_at':time.time()+60}), call_id))
        raise
    raw_usage = reply.get('usage')
    usage = {**(raw_usage if isinstance(raw_usage, dict) else {}), '_provider': provider}
    # Keep response before validating it; invalid outputs still incur usage.
    known_usage = valid_model_usage(usage)
    cost = 0 if spec['free'] else ((usage['prompt_tokens']*2 + usage['completion_tokens']*8)/1_000_000 if known_usage else reserve)
    with connect() as db:
        db.execute('UPDATE model_calls SET response=?,usage=?,model=?,estimated_cost=? WHERE id=?',
                   (json.dumps(reply, ensure_ascii=False), json.dumps(usage), reply.get('model', spec['model']), cost, call_id))
    if not known_usage:
        raise ValueError('模型响应用量缺失或无效，保留预算预留并暂停，请核验账单')
    return engine.parse_reply(reply)


def cached_judgment(batch_id, stage, prompt, content, threshold):
    cfg = analysis_config(batch_id)
    pool = cfg.get('provider_pool', [cfg.get('provider', 'deepseek')]) if cfg.get('fallback_enabled') else [cfg.get('provider', 'deepseek')]
    expected = {json.dumps({'system': engine.system_prompt(p), 'user': prompt}, ensure_ascii=False) for p in pool}
    with connect() as db:
        rows = db.execute('SELECT response,usage,prompt FROM model_calls WHERE batch_id=? AND stage=? ORDER BY id DESC', (batch_id, stage)).fetchall()
    for row in rows:
        if row['prompt'] not in expected:
            continue
        try:
            usage = json.loads(row['usage'])
            if not valid_model_usage(usage):
                continue
            payload = engine.parse_reply(json.loads(row['response']))
            if 'evidence_passages' in prompt:
                payload = engine.resolve_references(payload, prompt, content)
            return engine.validate_judgment(payload, content, threshold, require_scope='scope_relation' in prompt['schema'])
        except (ValueError, KeyError, TypeError, IndexError):
            continue
    return None


def analyze_record(batch_id, record, direction, key, cfg):
    def analyze(stage, prompt, content):
        existing = cached_judgment(batch_id, stage, prompt, content, cfg['threshold'])
        if existing is not None:
            return existing
        # Reuse a prior corrected response before requesting the same invalid format again.
        correction = {**prompt, 'format_correction': '严格遵守原schema。每个evidence字段最多500字符，reason最多1200字符，pain最多500字符，target_user最多200字符；引用仅选最小必要连续原文，不要复制整篇。function和industry只能各选一个合法标签。所有证据必须来自输入原文。上次输出未通过结构或证据校验，请重新输出完整JSON。'}
        existing = cached_judgment(batch_id, stage+':repair', correction, content, cfg['threshold'])
        if existing is not None:
            return existing
        references = engine.reference_prompt(prompt, content)
        reference_stage = stage+':evidence_refs_v1'
        final_prompt = {**references, 'schema_repair': '必须输出schema全部字段，不得遗漏任何_id字段；无证据用空字符串。scope_relation必须是direct/indirect/outside。每个值只用规定类型；不要增加字段。'}
        final_stage = stage+':schema_repair_v1'
        existing = cached_judgment(batch_id, final_stage, final_prompt, content, cfg['threshold'])
        if existing is not None:
            return existing
        existing = cached_judgment(batch_id, reference_stage, references, content, cfg['threshold'])
        if existing is not None:
            return existing
        with connect() as db:
            previous = db.execute('SELECT response FROM model_calls WHERE batch_id=? AND stage IN (?,?)',
                                  (batch_id, stage, stage+':repair')).fetchall()
        prior_failure = False
        for row in previous:
            try:
                response = json.loads(row['response'])
                if response.get('choices'):
                    prior_failure = True
            except (ValueError, KeyError, TypeError, IndexError):
                continue
        if not prior_failure:
            try:
                payload = request_analysis(batch_id, stage, prompt, 1600, key, cfg['budget_yuan'])
            except (engine.IncompleteReply, json.JSONDecodeError):
                payload = None
            if payload is not None:
                try:
                    return engine.validate_judgment(payload, content, cfg['threshold'], require_scope='scope_relation' in prompt['schema'])
                except ValueError:
                    pass
        # One closed-set correction; valid IDs resolve to exact source text, never fuzzy matching.
        try:
            payload = request_analysis(batch_id, reference_stage, references, 1600, key, cfg['budget_yuan'])
        except (engine.IncompleteReply, json.JSONDecodeError):
            payload = None
        if payload is not None:
            try:
                resolved = engine.resolve_references(payload, references, content)
                return engine.validate_judgment(resolved, content, cfg['threshold'], require_scope='scope_relation' in prompt['schema'])
            except ValueError:
                pass
        payload = request_analysis(batch_id, final_stage, final_prompt, 1600, key, cfg['budget_yuan'], preferred_provider='deepseek')
        return engine.validate_judgment(engine.resolve_references(payload, final_prompt, content), content, cfg['threshold'], require_scope=True)

    text = record['content']
    if len(text) <= 16000:
        return analyze('judge:'+record['id'], engine.judgment_prompt(record, direction), text)
    parts = engine.split_record(text)
    nodes = []
    for index, part in enumerate(parts, 1):
        prompt = engine.judgment_prompt({**record, 'content': part['content']}, direction)
        prompt['segment'] = {'version': engine.CHUNK_VERSION, 'index': index, 'total': len(parts),
                             'start': part['start'], 'end': part['end'], 'original_length': len(text),
                             'note': '同一长记录的局部片段；只判断本片段证据，不推断未提供的上下文'}
        result = analyze(f"judge:{record['id']}:part:{index:04d}", prompt, part['content'])
        nodes.append({'start': part['start'], 'end': part['end'], 'judgment': result})
    level = 0
    while len(nodes) > 1:
        level += 1
        merged = []
        for offset in range(0, len(nodes), 4):
            group = nodes[offset:offset+4]
            if len(group) == 1:
                merged.append(group[0])
                continue
            prompt = engine.merge_judgment_prompt(record, direction, group)
            prompt['chunk_version'] = engine.CHUNK_VERSION
            # Validate against the exact span represented by this merge, not unrelated text.
            start, end = group[0]['start'], group[-1]['end']
            result = analyze(f"judge:{record['id']}:merge:{level:02d}:{offset//4+1:04d}", prompt, text[start:end])
            merged.append({'start': start, 'end': end, 'judgment': result})
        nodes = merged
    result = nodes[0]['judgment']
    return {**result, 'long_text': {'version': engine.CHUNK_VERSION, 'original_characters': len(text),
                                  'segment_count': len(parts), 'overlap': 500,
                                  'offset_unit': 'Python Unicode字符，左闭右开',
                                  'segments': [{'start': p['start'], 'end': p['end']} for p in parts],
                                  'note': '全文分段读取并逐层汇总；汇总仍可能遗漏语义或误判，分段提示与回复均在调用日志中'}}


def verify_candidate(batch_id, record, direction, initial, key, cfg):
    provider = cfg.get('verification_provider', 'none')
    if not initial['opportunity'] or provider=='none':
        return initial
    prompt = engine.review_prompt(record, direction, initial)
    stage = 'verify:'+record['id']
    review = None
    repair_prompt = {**prompt, 'repair': '上次输出未通过schema/证据编号校验，请严格完整输出schema字段；support_ids只能选择已提供编号，不得添加字段。'}
    # Check BOTH cached attempts before making any new request.
    for cached_stage, cached_prompt in ((stage,prompt),(stage+':repair',repair_prompt)):
        expected=[json.dumps({'system':system,'user':cached_prompt},ensure_ascii=False) for system in (engine.system_prompt(provider,cached_prompt),engine.system_prompt(provider))]
        with connect() as db:
            rows=db.execute('SELECT response,usage FROM model_calls WHERE batch_id=? AND stage=? AND prompt IN (?,?) ORDER BY id DESC',(batch_id,cached_stage,*expected)).fetchall()
        for row in rows:
            try:
                usage=json.loads(row['usage'])
                if not valid_model_usage(usage):continue
                review=engine.validate_review(engine.parse_reply(json.loads(row['response'])),cached_prompt,record['content'])
                break
            except (ValueError,KeyError,TypeError,IndexError):continue
        if review is not None:break
    for attempt in range(0 if review is not None else 2):
        current = prompt if attempt==0 else {**prompt, 'repair': '上次输出未通过schema/证据编号校验，请严格完整输出schema字段；support_ids只能选择已提供编号，不得添加字段。'}
        current_stage = stage if attempt==0 else stage+':repair'
        if provider_cooldown(provider)>0:
            raise ValueError('候选复核模型冷却中，请稍后继续；不跳过独立复核')
        actual_key=key.get(provider,'') if isinstance(key,dict) else model_key(provider)
        if not actual_key:raise ValueError('未配置候选复核模型密钥')
        try:
            raw=request_provider(batch_id,current_stage,current,1200,actual_key,cfg['budget_yuan'],provider)
        except (engine.IncompleteReply,json.JSONDecodeError):
            if attempt==1:raise
            continue
        try:
            review=engine.validate_review(raw,current,record['content'])
            break
        except ValueError:
            if attempt==1:raise
    result={**initial,'verification':{**review,'version':engine.REVIEW_VERSION,'provider':provider,'model':engine.PROVIDERS[provider]['model']}}
    if not review['approved']:
        result.update(opportunity=0,excluded=True,function='',industry='',reason='独立复核未通过：'+review['reason'])
        if review['scope_relation']!='direct':result['relevant']=False
    return result


def judge_pending(batch_id, records, direction, key, cfg, judgments):
    """Keep at most N active records; stop scheduling on the first failure."""
    stop = threading.Event()
    ANALYSIS_STOPS[batch_id] = stop
    errors = []
    def work(record):
        try:
            result = analyze_record(batch_id, record, direction, key, cfg)
            result = verify_candidate(batch_id, record, direction, result, key, cfg)
            with connect() as db:
                db.execute('INSERT INTO judgments VALUES (?,?,?)',
                           (batch_id, record['id'], json.dumps(result, ensure_ascii=False)))
            return record['id'], result
        except Exception as exc:
            errors.append(exc)
            stop.set()
            raise
    pending = iter(r for r in records if r['id'] not in judgments)
    try:
        with ThreadPoolExecutor(max_workers=cfg.get('concurrency', 1)) as pool:
            active = set()
            def submit():
                record = next(pending, None)
                if record is not None and not stop.is_set():
                    active.add(pool.submit(work, record))
            for _ in range(cfg.get('concurrency', 1)):
                submit()
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        rid, result = future.result()
                        judgments[rid] = result
                    except Exception:
                        pass  # Retain first root cause; drain and save successful in-flight records.
                if not stop.is_set():
                    for _ in done:
                        submit()
        if errors:
            raise errors[0]
    finally:
        ANALYSIS_STOPS.pop(batch_id, None)


def run_analysis(batch_id, key):
    with ANALYSIS_LOCK:
        try:
            require_usable_batch(batch_id)
            batch, records = get_records(batch_id)
            state = analysis_state(batch_id)
            cfg = state['config']
            with connect() as db:
                db.execute("UPDATE analyses SET status='running',error='' WHERE batch_id=?", (batch_id,))
            judgments = state['judgments']
            judge_pending(batch_id, records, batch['direction'], key, cfg, judgments)
            positives = {k: judgments[k] for k in sorted(judgments) if judgments[k]['opportunity']}
            if positives:
                clusters = cached_clusters(batch_id, positives)
                if clusters is None:
                    payload = request_analysis(batch_id, 'cluster', cluster_request_prompt(batch_id, positives), 12000, key, cfg['budget_yuan'])
                    clusters = engine.validate_clusters(payload, positives)
            else:
                clusters = []
            with connect() as db:
                option = db.execute('SELECT sources FROM batch_options WHERE batch_id=?', (batch_id,)).fetchone()
            source_count = len({sources.NAMES[v] for v in json.loads(option[0])}) if option else 1
            ranked = engine.rank_clusters(clusters, records, source_count, (cfg['coverage_weight'], cfg['scale_weight']))
            metrics = {'opportunity_count': len(positives), 'record_count': len(records), 'cluster_count': len(ranked),
                       'singleton_clusters': sum(c['count'] == 1 for c in ranked),
                       'method': 'LLM语义聚类；使用独立原文TF-IDF词面向量评价结构，不代表语义正确率',
                       'score_formula': '覆盖分=100×簇内网站数/本批次选定网站数；规模分=100×log(1+簇记录数)/log(1+最大簇记录数)；加权平均',
                       'weight_rationale': f"研究配置：多源权重{cfg['coverage_weight']}、规模权重{cfg['scale_weight']}；初始默认0.6/0.4强调多源相互印证，属于待验证假设，需在论文中做敏感性分析。",
                       'confidence_note': '模型自评分，未经概率校准；阈值是可调研究假设，需用人工样本验证。'}
            with connect() as db:
                db.execute("UPDATE analyses SET status='complete',clusters=?,metrics=?,error='' WHERE batch_id=?",
                           (json.dumps(ranked, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False), batch_id))
        except Exception as exc:
            # Do not expose provider headers, key or arbitrary response bodies.
            message = str(exc) if isinstance(exc, ValueError) and not hasattr(exc, 'errors') else f'分析中断（{type(exc).__name__}）；已保存已完成步骤，可检查后继续'
            with connect() as db:
                db.execute("UPDATE analyses SET status='failed',error=? WHERE batch_id=?", (message[:1200], batch_id))


def cluster_request_prompt(batch_id, positives):
    prompt = engine.cluster_prompt(positives)
    with connect() as db:
        row = db.execute("SELECT response FROM model_calls WHERE batch_id=? AND stage='cluster' ORDER BY id DESC LIMIT 1", (batch_id,)).fetchone()
    if not row:
        return prompt
    try:
        previous = engine.parse_reply(json.loads(row['response']))
        engine.validate_clusters(previous, positives)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        if 'previous' not in locals() or not isinstance(previous, dict):
            return prompt
        # Feedback requests a fresh model partition; never invent membership locally.
        prompt['repair'] = {
            'version': 'cluster-feedback-v1',
            'instruction': '上次结果未通过校验。重新输出完整 clusters。先列清全部输入编号，再检查每个编号出现恰好一次；不能遗漏、重复或新增。只改分组，不要复述校验说明。',
            'required_record_ids': sorted(positives),
            'required_record_count': len(positives),
            'previous_invalid_output': previous,
            'validation_error': '结构、标签或成员完整性校验失败',
        }
        clusters = previous.get('clusters')
        if isinstance(clusters, list) and all(isinstance(c, dict) and isinstance(c.get('records'), list) and all(isinstance(r, str) for r in c['records']) for c in clusters):
            members = [r for c in clusters for r in c['records']]
            prompt['repair'].update(missing=sorted(set(positives)-set(members)),
                                    duplicated=sorted({r for r in members if members.count(r)>1}),
                                    unknown=sorted(set(members)-set(positives)))
    return prompt


def cached_clusters(batch_id, positives):
    """Recover a paid response after validator fixes without another model request."""
    with connect() as db:
        rows = db.execute("SELECT response FROM model_calls WHERE batch_id=? AND stage='cluster' ORDER BY id DESC", (batch_id,)).fetchall()
    for row in rows:
        try:
            return engine.validate_clusters(engine.parse_reply(json.loads(row['response'])), positives)
        except (ValueError, KeyError, TypeError, IndexError):
            continue
    return None


@app.post('/api/batches/{batch_id}/clone', status_code=201)
def clone_batch(batch_id: str):
    batch, records = get_records(batch_id)
    require_usable_batch(batch_id)
    if batch['status'] != 'collected' or not records:
        raise HTTPException(409, '只能复制已完成采集且有记录的批次')
    new_id = 'B'+uuid.uuid4().hex[:12].upper()
    with connect() as db:
        db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)',
                   (new_id, batch['direction'], batch['query'], batch['limit_count'], batch['days'],
                    datetime.now(timezone.utc).isoformat(), 'collected', ''))
        for table in ('records', 'batch_options', 'source_runs', 'record_meta'):
            columns = [r[1] for r in db.execute(f'PRAGMA table_info({table})') if r[1] != 'batch_id']
            names = ','.join(columns)
            db.execute(f'INSERT INTO {table}(batch_id,{names}) SELECT ?,{names} FROM {table} WHERE batch_id=?',
                       (new_id, batch_id))
    return {'id': new_id, 'copied_from': batch_id}


@app.post('/api/batches/{batch_id}/clone-available', status_code=201)
def clone_available(batch_id: str):
    """Create an explicitly scoped batch from complete, unambiguous websites only."""
    batch, records = get_records(batch_id)
    if batch['status'] != 'partial':
        raise HTTPException(409, '仅部分完成的采集批次可按成功来源复制')
    with connect() as db:
        option = db.execute('SELECT sources FROM batch_options WHERE batch_id=?', (batch_id,)).fetchone()
        run_rows = [dict(r) for r in db.execute('SELECT * FROM source_runs WHERE batch_id=?', (batch_id,))]
    selected = json.loads(option['sources']) if option else []
    runs = {r['source']: r for r in run_rows}
    groups = {}
    for source in selected:
        if source in sources.NAMES:
            groups.setdefault(sources.NAMES[source], []).append(source)
    unverified = {record['source'] for record in records if record['source']=='Node-RED Forum'
                  and not record['metadata'].get('provenance', {}).get('body_complete_verified')}
    accepted = [source for name,group in groups.items()
                if name not in unverified and all(source in runs and runs[source]['status']=='success'
                       and not source_policy.issues([source]) for source in group)
                for source in group]
    accepted_names = {sources.NAMES[source] for source in accepted}
    retained = [record for record in records if record['source'] in accepted_names]
    if not retained:
        raise HTTPException(409, '没有来源明确且完整成功的记录；请调整条件重新采集')
    excluded = [source for source in selected if source not in accepted]
    new_id = 'B' + uuid.uuid4().hex[:12].upper()
    with connect() as db:
        db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)',
                   (new_id, batch['direction'], batch['query'], batch['limit_count'], batch['days'],
                    datetime.now(timezone.utc).isoformat(), 'collected', ''))
        db.execute('INSERT INTO batch_options VALUES (?,?)', (new_id, json.dumps(accepted)))
        for source in accepted:
            meta = json.loads(runs[source]['metadata'])
            meta.update(recovered_from=batch_id, excluded_sources=excluded,
                        recovery_note='仅复制完整成功且同网站所有选定来源均成功的数据；Node-RED历史记录须有正文核验标记；不是重新采集')
            db.execute('INSERT INTO source_runs VALUES (?,?,?,?)',
                       (new_id, source, 'success', json.dumps(meta, ensure_ascii=False)))
        for index, record in enumerate(retained, 1):
            new_record_id = f'S{index:05d}'
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (new_id, new_record_id, record['source'], record['url'], record['title'],
                        record['raw_text'], record['content'], record['published_at'], record['updated_at'],
                        record['stars'], record['collected_at']))
            metadata = {**record['metadata'], 'lineage': {'batch_id': batch_id, 'record_id': record['id']}}
            db.execute('INSERT INTO record_meta VALUES (?,?,?)',
                       (new_id, new_record_id, json.dumps(metadata, ensure_ascii=False)))
    return {'id': new_id, 'copied_from': batch_id, 'included_sources': accepted,
            'excluded_sources': excluded, 'record_count': len(retained)}


@app.post('/api/batches/{batch_id}/analyze', status_code=202)
def start_analysis(batch_id: str, body: AnalysisInput, background: BackgroundTasks):
    batch, records = get_records(batch_id)
    require_usable_batch(batch_id)
    state = analysis_state(batch_id)
    if state and state['retry_after_seconds'] > 0 and not body.fallback_enabled:
        raise HTTPException(429, f"模型服务冷却中，请 {state['retry_after_seconds']} 秒后继续；已完成判别会复用")
    if batch['status'] != 'collected':
        raise HTTPException(409, '请先完成全部选定来源的采集；部分失败的批次不启动完整分析')
    if not records:
        raise HTTPException(409, '没有可分析记录，请调整关键词采集')
    provider = MODEL_PROVIDER
    key = model_key(provider)
    if not key:
        raise HTTPException(409, '请由管理员在模型与团队设置中配置所选服务的 API Key')
    config = {**body.model_dump(), 'prompt_version': engine.PROMPT_VERSION, 'model': engine.PROVIDERS[provider]['model']}
    if body.verification_provider != 'none':
        config['verification_version'] = engine.REVIEW_VERSION
    if body.verification_provider!='none' and not model_key(body.verification_provider):
        raise HTTPException(409, '请先配置候选复核服务的API Key')
    if body.fallback_enabled:
        pool = [provider]+[p for p in engine.PROVIDERS if p != provider and model_key(p)]
        if len(pool) < 2:
            raise HTTPException(409, '启用自动切换前，请配置至少两个模型服务的密钥')
        config['provider_pool'] = pool
        key = {p: model_key(p) for p in pool}
    if body.verification_provider!='none':
        if not isinstance(key,dict):key={provider:key}
        key[body.verification_provider]=model_key(body.verification_provider)
    if provider != 'deepseek':
        config['provider'] = provider
        config['prompt_version'] = engine.PROVIDERS[provider]['prompt_version']
    if any(len(r['content']) > 16000 for r in records):
        config['long_text_version'] = engine.CHUNK_VERSION
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT * FROM analyses WHERE batch_id=?', (batch_id,)).fetchone()
        if existing:
            if existing['status'] in ('queued', 'running', 'complete'):
                raise HTTPException(409, '该批次正在分析或已完成，不重复付费调用')
            old = json.loads(existing['config'])
            if body.verification_provider != 'none' and old.get('verification_version') != engine.REVIEW_VERSION:
                raise HTTPException(409, '候选复核规则版本已变化或旧批次未记录版本；请复制资料用于新分析，避免混合实验方法')
            if any(old.get(k) != v for k, v in config.items() if k not in ('budget_yuan', 'concurrency', 'fallback_enabled', 'provider_pool')):
                raise HTTPException(409, '续跑需保持原判别与评分配置，可调整预算与并发数；更换模型请先复制资料用于新分析')
            db.execute("UPDATE analyses SET status='queued',config=?,error='' WHERE batch_id=?", (json.dumps(config), batch_id))
        else:
            db.execute("INSERT INTO analyses(batch_id,status,config) VALUES (?,'queued',?)", (batch_id, json.dumps(config)))
    background.add_task(run_analysis, batch_id, key)
    return {'status': 'queued'}


def completed_analysis(batch_id):
    get_records(batch_id)
    require_usable_batch(batch_id)
    state = analysis_state(batch_id)
    if not state or state['status'] != 'complete':
        raise HTTPException(409, '全部分析成功后才能导出最终结果')
    return state


def run_stability(batch_id, provider, key, positives, budget):
    """Two fresh, unassisted partitions; rejected outputs remain in the audit log."""
    with ANALYSIS_LOCK:
        with STABILITY_LOCK:
            STABILITY_JOBS[batch_id]['status'] = 'running'
        try:
            prompt = engine.cluster_prompt(positives)
            for attempt in range(4):
                payload = request_provider(batch_id, 'cluster', prompt, 12000, key, budget, provider)
                with STABILITY_LOCK:
                    STABILITY_JOBS[batch_id]['attempts'] = attempt + 1
                try:
                    engine.validate_clusters(payload, positives)
                except (ValueError, KeyError, TypeError):
                    continue
                with STABILITY_LOCK:
                    STABILITY_JOBS[batch_id]['valid_runs'] += 1
                    if STABILITY_JOBS[batch_id]['valid_runs'] == 2:
                        STABILITY_JOBS[batch_id]['status'] = 'complete'
                        return
            raise ValueError('四次独立聚类中有效结果不足两次，请检查模型输出后再试')
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) and not hasattr(exc, 'errors') else f'独立聚类中断（{type(exc).__name__}）'
            with STABILITY_LOCK:
                STABILITY_JOBS[batch_id].update(status='failed', error=message[:500])


@app.post('/api/batches/{batch_id}/stability-run', status_code=202)
def start_stability(batch_id: str, body: StabilityInput, background: BackgroundTasks):
    state = completed_analysis(batch_id)
    positives = {k: v for k, v in sorted(state['judgments'].items()) if v['opportunity']}
    if len(positives) < 2:
        raise HTTPException(409, '至少需要两条候选记录才能比较聚类')
    key = model_key(body.provider)
    if not key:
        raise HTTPException(409, '请先配置所选模型的 API Key')
    with STABILITY_LOCK:
        current = STABILITY_JOBS.get(batch_id, {})
        if current.get('status') in ('queued', 'running'):
            raise HTTPException(409, '该批次的独立聚类已在运行')
        if body.budget_yuan is not None:
            state['config']['budget_yuan'] = body.budget_yuan
            with connect() as db:
                db.execute('UPDATE analyses SET config=? WHERE batch_id=?',
                           (json.dumps(state['config'], ensure_ascii=False), batch_id))
        STABILITY_JOBS[batch_id] = {'status': 'queued', 'provider': body.provider,
                                    'attempts': 0, 'valid_runs': 0, 'error': ''}
    background.add_task(run_stability, batch_id, body.provider, key, positives, state['config']['budget_yuan'])
    return {'status': 'queued'}


@app.get('/api/batches/{batch_id}/stability-run')
def stability_status(batch_id: str):
    completed_analysis(batch_id)
    with STABILITY_LOCK:
        return dict(STABILITY_JOBS.get(batch_id, {'status': 'idle', 'attempts': 0, 'valid_runs': 0, 'error': ''}))


def csv_download(header, rows, filename):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows([[csv_safe(v) for v in row] for row in rows])
    return Response(stream.getvalue().encode('utf-8-sig'), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.get('/api/batches/{batch_id}/result2.csv')
def export2(batch_id: str):
    state = completed_analysis(batch_id)
    return csv_download(['采集批次号','记录编号','是否构成机会','机会置信度','功能类别','所属行业'],
                        [[batch_id, rid, j['opportunity'], j['confidence'], j['function'], j['industry']] for rid,j in sorted(state['judgments'].items())], 'result2.csv')


@app.get('/api/batches/{batch_id}/result3.csv')
def export3(batch_id: str):
    state = completed_analysis(batch_id)
    return csv_download(['采集批次号','主题簇编号','主题簇名称','功能类别','所属行业','簇内机会记录数','来源覆盖','簇内机会记录'],
                        [[batch_id,c['id'],c['name'],c['function'],c['industry'],c['count'],'；'.join(c['sources']),'；'.join(c['records'])] for c in state['clusters']], 'result3.csv')


@app.get('/api/batches/{batch_id}/result4.csv')
def export4(batch_id: str):
    state = completed_analysis(batch_id)
    return csv_download(['采集批次号','主题簇编号','主题簇名称','功能类别','所属行业','机会价值分','优先级'],
                        [[batch_id,c['id'],c['name'],c['function'],c['industry'],c['score'],c['priority']] for c in state['clusters']], 'result4.csv')


@app.get('/api/batches/{batch_id}/clusters/{cluster_id}/proposal.md')
def export_proposal(batch_id: str, cluster_id: str):
    state = completed_analysis(batch_id)
    cluster = next((c for c in state['clusters'] if c['id'] == cluster_id), None)
    if not cluster:
        raise HTTPException(404, '主题簇不存在')
    batch, records = get_records(batch_id)
    text = engine.proposal(batch, cluster, state['judgments'], records)
    return Response(text.encode('utf-8-sig'), media_type='text/markdown', headers={'Content-Disposition': 'attachment; filename="proposal.md"'})


class ReviewInput(BaseModel):
    record_id: str
    label: Literal[0, 1]
    reason: str = Field(min_length=2, max_length=1000)


@app.post('/api/batches/{batch_id}/reviews')
def review(batch_id: str, body: ReviewInput, request: Request):
    _, records = get_records(batch_id)
    if body.record_id not in {r['id'] for r in records}:
        raise HTTPException(404, '记录不存在')
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)', (batch_id, body.record_id, request.state.user['username'], body.label, body.reason, datetime.now(timezone.utc).isoformat()))
    return {'ok': True}


class PairReview(BaseModel):
    left_id: str
    right_id: str
    same_topic: Literal[0, 1]


@app.post('/api/batches/{batch_id}/pair-reviews')
def pair_review(batch_id: str, body: PairReview, request: Request):
    state = completed_analysis(batch_id)
    ids = {rid for c in state['clusters'] for rid in c['records']}
    if body.left_id == body.right_id or not {body.left_id, body.right_id} <= ids:
        raise HTTPException(422, '请选择两个不同的机会记录')
    left, right = sorted([body.left_id, body.right_id])
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO pair_reviews VALUES (?,?,?,?,?)', (batch_id, left, right, request.state.user['username'], body.same_topic))
    return {'ok': True}


# Offline research pipeline with separate, versioned experiment history.
local_routes.install(app, connect, get_records, require_usable_batch, ROOT, sources, csv_download)
