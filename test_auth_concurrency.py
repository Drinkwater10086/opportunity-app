"""Concurrent local account operations, using fixture-isolated data only."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import threading
from fastapi import HTTPException, Request, Response
import app
import auth
from test_pipeline import client


def test_parallel_bad_passwords_cannot_lose_rate_limit_counter(client):
    endpoint=next(r.endpoint for r in app.app.routes if getattr(r,'path',None)=='/api/login')
    gate=threading.Barrier(8,timeout=5)
    lock=threading.Lock()
    calls=0
    def digest(*args):
        nonlocal calls
        with lock:
            calls+=1
            current=calls
        if current<=8:
            gate.wait()
        return 'wrong-hash'
    def attempt(_):
        request=Request({'type':'http','client':('parallel-login-test',1),'headers':[]})
        try:
            endpoint(auth.Credentials(username='tester',password='wrong-test-password'),Response(),request)
        except HTTPException as exc:
            return exc.status_code
    with patch.object(auth,'digest',side_effect=digest),ThreadPoolExecutor(8) as pool:
        assert list(pool.map(attempt,range(8)))==[401]*8
        assert attempt(9)==429


def test_parallel_user_creation_returns_conflict_not_database_error(client):
    endpoint=next(r.endpoint for r in app.app.routes if getattr(r,'path',None)=='/api/users')
    barrier=threading.Barrier(2,timeout=5)
    def create(_):
        barrier.wait()
        try:
            endpoint(auth.NewUser(username='concurrent-user',password='synthetic-password',role='researcher'))
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(create,range(2)))==[200,409]
