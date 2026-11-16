import json
import subprocess
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import github_access
import sources


def reply(status=200, headers=None, message=''):
    response = Mock(status_code=status, headers=headers or {})
    response.json.return_value = {'items': [], 'total_count': 0, 'message': message}
    return response


@pytest.fixture
def clock(monkeypatch):
    value = [1000.0]
    sleeps = []
    monkeypatch.setattr(sources, '_cooldown', {})
    monkeypatch.setattr(sources.time, 'monotonic', lambda: value[0])
    monkeypatch.setattr(sources.time, 'time', lambda: value[0])
    def sleep(seconds):
        sleeps.append(seconds)
        value[0] += seconds
    monkeypatch.setattr(sources.time, 'sleep', sleep)
    return value, sleeps


def page():
    return sources.fetch_page('github', 'meeting', 2, 30,
                              window_end=datetime(2026, 11, 16, tzinfo=timezone.utc))


def test_existing_git_login_is_noninteractive_cached_and_not_persisted(monkeypatch):
    monkeypatch.setenv('OPPORTUNITY_GITHUB_USE_GIT_CREDENTIALS', '1')
    monkeypatch.setattr(github_access, '_cached', (0, '', 'anonymous'))
    run = Mock(return_value=Mock(returncode=0, stdout='username=example\npassword=synthetic-test-token\n'))
    monkeypatch.setattr(github_access.subprocess, 'run', run)
    assert github_access.credentials() == ('synthetic-test-token', 'git_credential_helper')
    assert github_access.credentials()[0] == 'synthetic-test-token'
    run.assert_called_once()
    assert run.call_args.args[0] == ['git', 'credential', 'fill']
    options = run.call_args.kwargs
    assert options['input'] == 'protocol=https\nhost=github.com\n\n'
    assert options['env']['GCM_INTERACTIVE'] == 'Never'
    assert options['env']['GIT_TERMINAL_PROMPT'] == '0'
    assert options['capture_output'] is True
    assert options['timeout'] == 8


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('git', 8)])
def test_missing_or_hung_git_falls_back_to_anonymous(monkeypatch, error):
    monkeypatch.setenv('OPPORTUNITY_GITHUB_USE_GIT_CREDENTIALS', '1')
    monkeypatch.setattr(github_access, '_cached', (0, '', 'anonymous'))
    monkeypatch.setattr(github_access.subprocess, 'run', Mock(side_effect=error))
    assert github_access.credentials() == ('', 'anonymous')


def test_environment_token_takes_precedence(monkeypatch):
    monkeypatch.setenv('OPPORTUNITY_GITHUB_TOKEN', 'synthetic-env-token')
    run = Mock()
    monkeypatch.setattr(github_access.subprocess, 'run', run)
    assert github_access.credentials() == ('synthetic-env-token', 'server_environment')
    run.assert_not_called()


def test_disabled_git_reuse_does_not_read_local_credentials(monkeypatch):
    run = Mock()
    monkeypatch.setattr(github_access.subprocess, 'run', run)
    assert github_access.credentials() == ('', 'anonymous')
    run.assert_not_called()


def test_invalid_rate_headers_use_bounded_default():
    assert github_access.rate_delay(reply(429, {'Retry-After': 'inf'}), 0) == 60
    assert github_access.rate_delay(reply(403, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': 'nan'}), 0) == 60


def test_authenticated_search_public_only_and_no_secret_in_metadata(monkeypatch, clock):
    monkeypatch.setenv('OPPORTUNITY_GITHUB_TOKEN', 'synthetic-env-token')
    get = Mock(return_value=reply())
    monkeypatch.setattr(sources.requests, 'get', get)
    _, metadata = page()
    kwargs = get.call_args.kwargs
    assert kwargs['headers']['Authorization'] == 'Bearer synthetic-env-token'
    assert kwargs['allow_redirects'] is False
    assert 'is:public' in kwargs['params']['q']
    assert metadata['authentication'] == 'server_environment'
    assert 'synthetic-env-token' not in json.dumps(metadata)


@pytest.mark.parametrize('source', ['github', 'github_issues'])
def test_private_records_are_rejected(monkeypatch, clock, source):
    response = reply()
    response.json.return_value['items'] = [{'private': True}]
    monkeypatch.setattr(sources.requests, 'get', Mock(return_value=response))
    with pytest.raises(ValueError, match='非公开'):
        sources.fetch_page(source, 'test', 1, 30)


def test_primary_limit_waits_for_reset_then_retries(monkeypatch, clock):
    get = Mock(side_effect=[reply(403, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1010'}), reply()])
    monkeypatch.setattr(sources.requests, 'get', get)
    _, meta = page()
    assert get.call_count == 2 and meta['request_attempts'] == 2
    assert clock[0][0] == 1011
    assert max(clock[1]) <= 30


def test_secondary_limit_obeys_retry_after_and_shared_pacing(monkeypatch, clock):
    get = Mock(side_effect=[reply(429, {'Retry-After': '9'}), reply(), reply()])
    monkeypatch.setattr(sources.requests, 'get', get)
    page()
    sources.fetch_page('github_issues', 'meeting', 2, 30)
    assert clock[0][0] == 1017  # 10 seconds backoff and 7 seconds anonymous spacing
    assert get.call_count == 3


@pytest.mark.parametrize('status,message', [(401, '凭据已失效'), (403, '拒绝搜索访问'), (302, '意外跳转')])
def test_auth_permission_redirect_errors_are_not_retried(monkeypatch, clock, status, message):
    get = Mock(return_value=reply(status))
    monkeypatch.setattr(sources.requests, 'get', get)
    with pytest.raises(ValueError, match=message):
        page()
    assert get.call_count == 1


def test_long_limit_stops_without_ignoring_cooldown(monkeypatch, clock):
    get = Mock(return_value=reply(429, {'Retry-After': '120'}))
    monkeypatch.setattr(sources.requests, 'get', get)
    with pytest.raises(ValueError, match='搜索限流'):
        page()
    with pytest.raises(ValueError, match='请求冷却中'):
        page()
    assert get.call_count == 1 and not clock[1]


def test_retry_budget_is_bounded(monkeypatch, clock):
    get = Mock(return_value=reply(429, {'Retry-After': '0'}))
    monkeypatch.setattr(sources.requests, 'get', get)
    with pytest.raises(ValueError, match='搜索限流'):
        page()
    assert get.call_count == 3


def test_secondary_limit_without_headers_waits_a_minute(monkeypatch, clock):
    get = Mock(side_effect=[reply(403, message='You have exceeded a secondary rate limit.'), reply()])
    monkeypatch.setattr(sources.requests, 'get', get)
    page()
    assert clock[0][0] == 1060
    assert clock[1] == [30, 30]


def test_success_with_zero_quota_delays_following_issue_search(monkeypatch, clock):
    get = Mock(side_effect=[reply(headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1010'}), reply()])
    monkeypatch.setattr(sources.requests, 'get', get)
    page()
    sources.fetch_page('github_issues', 'test', 1, 30)
    assert clock[0][0] == 1011


def test_partial_pages_retained_after_long_rate_limit(monkeypatch, clock):
    first = reply()
    first.json.return_value['total_count'] = 500
    get = Mock(side_effect=[first, reply(429, {'Retry-After': '120'})])
    monkeypatch.setattr(sources.requests, 'get', get)
    _, metadata = sources.fetch('github', 'meeting', 200, 30)
    assert metadata['complete'] is False and len(metadata['pages']) == 1
    assert '搜索限流' in metadata['error']


def test_credentials_cannot_be_sent_to_other_endpoints(monkeypatch, clock):
    get = Mock()
    monkeypatch.setattr(sources.requests, 'get', get)
    with pytest.raises(ValueError, match='不支持'):
        sources._github_request('https://example.com', {}, {})
    get.assert_not_called()
