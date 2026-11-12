import pytest
import sources


@pytest.mark.parametrize('text,secret',[
    ('Authorization: Bearer synthetic_credential_123456','synthetic_credential_123456'),
    ('api_key="synthetic_credential_123456"','synthetic_credential_123456'),
    ('{"access_token": "synthetic_credential_123456"}','synthetic_credential_123456'),
    ('Phone: +1 (212) 555-0199','555-0199'),
    ('联系电话：010-12345678','010-12345678'),
])
def test_explicit_credentials_and_phone_labels_are_redacted(text,secret):
    assert secret not in sources.redact(text)


def test_redaction_preserves_technical_metrics_and_is_idempotent():
    text='HTTP 503; 16000 characters; 2026-11-10; 120000 tokens; test@example.com'
    cleaned=sources.redact(text)
    for retained in ('HTTP 503','16000','2026-11-10','120000 tokens'):
        assert retained in cleaned
    assert 'test@example.com' not in cleaned
    assert sources.redact(cleaned)==cleaned


@pytest.mark.parametrize('text,secret',[
    ('Contact me at +1 (212) 555-0199 for details','555-0199'),
    ('Reach us via 212-555-0199 during office hours','212-555-0199'),
])
def test_unlabelled_formatted_phone_numbers_are_redacted(text,secret):
    assert secret not in sources.redact(text)


def test_dates_and_short_technical_numbers_are_not_mistaken_for_phone_numbers():
    text='Release 2026-11-12; +1 day; HTTP 503; build 2024-10-31.'
    assert sources.redact(text)==text
