"""Keep unit tests independent of the maintainer's real GitHub credentials."""
import pytest


@pytest.fixture(autouse=True)
def isolated_github_credentials(monkeypatch):
    monkeypatch.delenv('OPPORTUNITY_GITHUB_TOKEN', raising=False)
    monkeypatch.setenv('OPPORTUNITY_GITHUB_USE_GIT_CREDENTIALS', '0')
