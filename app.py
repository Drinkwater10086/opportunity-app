"""Public-source collection, independent batches, traceable analysis and exports."""
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
from typing import Literal

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
import sources
import source_policy
import auth
import local_routes
import source_catalog
import collection_screening

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LOCK = threading.Lock()


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
        CREATE TABLE IF NOT EXISTS reviews(batch_id TEXT NOT NULL,record_id TEXT NOT NULL,reviewer TEXT NOT NULL,label INTEGER NOT NULL,reason TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(batch_id,record_id,reviewer),FOREIGN KEY(batch_id,record_id) REFERENCES records(batch_id,id));
        CREATE TABLE IF NOT EXISTS pair_reviews(batch_id TEXT NOT NULL REFERENCES batches(id),left_id TEXT NOT NULL,right_id TEXT NOT NULL,reviewer TEXT NOT NULL,same_topic INTEGER NOT NULL,PRIMARY KEY(batch_id,left_id,right_id,reviewer));
        ''')
        auth.init(db)
        local_routes.init(db)
        db.execute("UPDATE batches SET status='failed',error='上次运行中断，请新建批次重试' WHERE status IN ('queued','running')")


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
    sources: list[Literal['github', 'github_issues', 'stackoverflow', 'hackernews', 'superuser', 'workplace', 'n8n', 'make', 'nodered', 'v2ex', 'arxiv', 'ithome', 'kaggle', 'producthunt', 'infoq', 'qbitai']] = Field(default=['github'], min_length=1, max_length=16)


def clean(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'https?://\S+', '', text).replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[^\S\n]+', ' ', text)
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text).strip()


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
                rows, meta_rows, screening_reports = [], [], []
                pending_seen, pending_urls = set(), set()
                pending_count = count
                for item in items:
                    content = clean(item['title'] + '\n' + item['raw_text'])
                    key = content.casefold()
                    if key in seen or key in pending_seen or item['url'] in urls or item['url'] in pending_urls:
                        continue
                    pending_seen.add(key)
                    pending_urls.add(item['url'])
                    screening = collection_screening.inspect(item['title'], content, item.get('provenance', {}))
                    screening_reports.append(screening)
                    pending_count += 1
                    rid = f'S{pending_count:05d}'
                    rows.append((batch_id, rid, sources.NAMES[source], item['url'], item['title'],
                                 item['raw_text'], content, item['published_at'], item['updated_at'],
                                 item['stars'], datetime.now(timezone.utc).isoformat()))
                    meta_rows.append((batch_id, rid, json.dumps({'heat': item['heat'], 'license': item['license'],
                        'collection_screening': screening,
                        'provenance': item.get('provenance', {}),
                        'reliability': item.get('reliability', {}),
                        'privacy': {'method': 'rule-redaction-v3', 'complete_personal_data_detection': False,
                                    'note': '规则移除常见联系方式与凭据；姓名、签名、住址等自由文本仍可能残留，不能视为完整匿名化'},
                        'transformations': 'HTML转文本（如适用）、明显联系方式脱敏、Unicode及空白规范化、清洗文本去URL'}, ensure_ascii=False)))
                metadata['kept_count'] = len(rows)
                metadata['deduplicated_count'] = len(items)-len(rows)
                metadata['content_screening'] = collection_screening.summarize(screening_reports)
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


@app.get('/api/source-catalog')
def catalog():
    return source_catalog.report()


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
    return {'batch': batch, 'records': records, 'sources': logs,
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
    return Response(json.dumps(data, ensure_ascii=False, indent=2),
                    media_type='application/json', headers={'Content-Disposition': 'attachment; filename="evidence.json"'})


@app.get('/api/batches/{batch_id}/collection-evidence.json')
def collection_evidence(batch_id: str):
    batch, records = get_records(batch_id)
    with connect() as db:
        source_runs = [dict(row) for row in db.execute('SELECT * FROM source_runs WHERE batch_id=?', (batch_id,))]
    return Response(json.dumps({'batch':batch,'records':records,'sources':source_runs},ensure_ascii=False,indent=2),
                    media_type='application/json',headers={'Content-Disposition':'attachment; filename="collection-evidence.json"'})


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


def csv_download(header, rows, filename):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows([[csv_safe(v) for v in row] for row in rows])
    return Response(stream.getvalue().encode('utf-8-sig'), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


# Program analysis with independent, versioned run history.
local_routes.install(app, connect, get_records, require_usable_batch, ROOT, sources, csv_download)
