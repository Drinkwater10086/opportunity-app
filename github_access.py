"""Server-only GitHub credentials and documented rate-limit classification."""
import os
import math
import subprocess
import threading
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

_lock = threading.Lock()
_cached = (0, '', 'anonymous')


def credentials():
    """Reuse an existing Git login without prompting or persisting its token."""
    token = os.environ.get('OPPORTUNITY_GITHUB_TOKEN', '').strip()
    if token:
        if any(c.isspace() for c in token):
            raise ValueError('服务器 GitHub 凭据格式无效')
        return token, 'server_environment'
    if os.environ.get('OPPORTUNITY_GITHUB_USE_GIT_CREDENTIALS', '1') == '0':
        return '', 'anonymous'
    global _cached
    with _lock:
        if time.monotonic() < _cached[0]:
            return _cached[1:]
        token = ''
        try:
            result = subprocess.run(
                ['git', 'credential', 'fill'],
                input='protocol=https\nhost=github.com\n\n',
                text=True, capture_output=True, timeout=8,
                env={**os.environ, 'GCM_INTERACTIVE': 'Never',
                     'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '', 'SSH_ASKPASS': ''})
            if result.returncode == 0:
                fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
                candidate = fields.get('password', '')
                if candidate and not any(c.isspace() for c in candidate):
                    token = candidate
        except (OSError, subprocess.SubprocessError):
            pass
        mode = 'git_credential_helper' if token else 'anonymous'
        _cached = (time.monotonic() + 60, token, mode)
        return token, mode


def response_headers(response):
    headers = getattr(response, 'headers', {})
    return headers if isinstance(headers, Mapping) else {}


def rate_delay(response, attempt):
    """None means a permission error; a number means a rate-limit wait."""
    headers = response_headers(response)
    try:
        payload = response.json()
        message = str(payload.get('message', '')).lower() if isinstance(payload, dict) else ''
    except ValueError:
        message = ''
    if (response.status_code != 429 and headers.get('X-RateLimit-Remaining') != '0'
            and 'rate limit' not in message and 'abuse detection' not in message):
        return None
    waits = []
    retry = headers.get('Retry-After')
    if retry is not None:
        try:
            seconds = float(retry)
            if math.isfinite(seconds):
                waits.append(max(0, seconds))
        except (TypeError, ValueError):
            try:
                waits.append(max(0, parsedate_to_datetime(retry).timestamp() - time.time()))
            except (TypeError, ValueError, OverflowError):
                pass
    if headers.get('X-RateLimit-Remaining') == '0':
        try:
            seconds = float(headers['X-RateLimit-Reset']) - time.time()
            if math.isfinite(seconds):
                waits.append(max(0, seconds))
        except (KeyError, TypeError, ValueError):
            pass
    return max(waits) + 1 if waits else 60 * (2 ** attempt)
