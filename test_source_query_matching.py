import pytest
from sources import matches_local_query


@pytest.mark.parametrize('text',['email delivery','chair purchase','staircase','storage needs','my_AI_module'])
def test_ai_and_rag_do_not_match_unrelated_word_substrings(text):
    assert not matches_local_query(text,'AI')
    assert not matches_local_query(text,'RAG')


@pytest.mark.parametrize('text',['AI会议记录','使用AI处理邮件','AI-powered summaries','LLM and AI tools','ai workflow'])
def test_ai_boundaries_keep_chinese_and_hyphenated_mentions(text):
    assert matches_local_query(text,'AI')


def test_local_token_and_semantics_remain_explicit():
    assert matches_local_query('AI records会议 using Whisper','AI Whisper')
    assert not matches_local_query('AI meeting reports','AI Whisper')
    assert matches_local_query('团队会议转写需求','会议 转写')
    assert not matches_local_query('ordinary text','')
    # Advanced API quotes are not silently interpreted by local feed filtering.
    assert not matches_local_query('AI meeting','"AI"')
