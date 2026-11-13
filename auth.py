"""Local accounts, hashed passwords and expiring cookie sessions."""
import hashlib
import hmac
import secrets
import time
import threading
from typing import Literal
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class Credentials(BaseModel):
    username: str = Field(pattern=r'^[A-Za-z0-9_-]{3,32}$')
    password: str = Field(min_length=10, max_length=128)


class NewUser(Credentials):
    role: Literal['researcher', 'decision']


def digest(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()


def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,salt TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,username TEXT REFERENCES users(username),expires REAL NOT NULL);
    ''')


def install(app, connect):
    attempts = {}
    attempts_lock = threading.Lock()

    @app.middleware('http')
    async def authenticate(request, call_next):
        path = request.url.path
        if path.startswith('/api/') and path not in ('/api/session', '/api/login', '/api/setup'):
            token = request.cookies.get('opportunity_session', '')
            with connect() as db:
                user = db.execute('SELECT u.username,u.role FROM sessions s JOIN users u ON u.username=s.username WHERE token_hash=? AND expires>?',
                                  (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            if not user:
                return JSONResponse({'detail': '请先登录'}, status_code=401)
            request.state.user = dict(user)
            if request.method != 'GET':
                admin_only = path in ('/api/config', '/api/users')
                research_only = path == '/api/batches' or path.endswith(('/analyze', '/clone', '/clone-available', '/stability-run'))
                if (admin_only and user['role'] != 'admin') or (research_only and user['role'] == 'decision'):
                    return JSONResponse({'detail': '当前角色没有此操作权限'}, status_code=403)
        return await call_next(request)

    @app.get('/api/session')
    def session(request: Request):
        token = request.cookies.get('opportunity_session', '')
        with connect() as db:
            setup = db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
            user = db.execute('SELECT u.username,u.role FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires>?',
                              (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return {'needs_setup': setup, 'user': dict(user) if user else None}

    @app.post('/api/setup')
    def setup(body: Credentials):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                raise HTTPException(409, '管理员已创建')
            salt = secrets.token_hex(16)
            db.execute('INSERT INTO users VALUES (?,?,?,?)', (body.username, salt, digest(body.password, salt), 'admin'))
        return {'ok': True}

    @app.post('/api/login')
    def login(body: Credentials, response: Response, request: Request):
        address = request.client.host if request.client else 'local'
        # Reserve before password work: concurrent failures must not overwrite each other.
        with attempts_lock:
            now = time.time()
            failed = [t for t in attempts.get(address, []) if t > now-60]
            if len(failed) >= 8:
                raise HTTPException(429, '登录尝试过多，请一分钟后重试')
            attempts[address] = failed + [now]
        with connect() as db:
            user = db.execute('SELECT * FROM users WHERE username=?', (body.username,)).fetchone()
            if not user or not hmac.compare_digest(digest(body.password, user['salt']), user['password_hash']):
                raise HTTPException(401, '用户名或密码错误')
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), body.username, time.time()+8*3600))
        with attempts_lock:
            attempts.pop(address, None)
        response.set_cookie('opportunity_session', token, httponly=True, samesite='strict', max_age=8*3600)
        return {'username': body.username, 'role': user['role']}

    @app.post('/api/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get('opportunity_session', '')
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie('opportunity_session')
        return {'ok': True}

    @app.post('/api/users')
    def new_user(body: NewUser):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users WHERE username=?', (body.username,)).fetchone():
                raise HTTPException(409, '用户名已存在')
            salt = secrets.token_hex(16)
            db.execute('INSERT INTO users VALUES (?,?,?,?)', (body.username, salt, digest(body.password, salt), body.role))
        return {'ok': True}
