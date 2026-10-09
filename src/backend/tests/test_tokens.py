"""Real token counts replace UTF-8 byte estimates (ARA-076)."""

PROSE = (
    "Retrieval-augmented generation combines a parametric language model with a "
    "non-parametric memory of documents. Given a question, a retriever selects the "
    "passages most likely to contain the answer, and the generator conditions on them "
    "while it writes. The approach reduces hallucination on knowledge-intensive tasks "
    "and makes each answer traceable to its sources. Dense retrievers embed questions "
    "and passages in a shared vector space, while sparse retrievers match weighted "
    "terms. Hybrid systems fuse both rankings, often with reciprocal rank fusion, and "
    "may rerank the fused candidates with a cross-encoder before generation. "
) * 4


def test_given_o200k_when_counting_then_real_tokens_are_returned():
    from app.integrations.tokens import TiktokenCounter

    assert TiktokenCounter("o200k_base").count("hello world") == 2


def test_given_local_factor_when_counting_then_tokens_scale_and_round_up():
    from app.integrations.tokens import TiktokenCounter

    assert TiktokenCounter("o200k_base").count(" word" * 1000) == 1000
    assert TiktokenCounter("o200k_base", factor=1.05).count(" word" * 1000) == 1050
    assert TiktokenCounter("o200k_base", factor=1.05).count(" word" * 999) == 1049
    assert TiktokenCounter("o200k_base", factor=1.018).count(" word" * 1000) == 1018


def test_given_english_prose_when_counting_then_far_fewer_tokens_than_bytes():
    from app.integrations.tokens import TiktokenCounter

    assert len(PROSE) >= 2000
    for counter in (TiktokenCounter("o200k_base"), TiktokenCounter("o200k_base", factor=1.05)):
        assert counter.count(PROSE) * 3 <= len(PROSE.encode("utf-8"))


def test_given_messages_when_counting_then_role_framing_is_included():
    from app.integrations.tokens import (
        MESSAGE_OVERHEAD,
        PromptMessage,
        TiktokenCounter,
        count_messages,
    )

    messages = [PromptMessage("system", "hello world"), PromptMessage("user", "hello world")]
    assert MESSAGE_OVERHEAD == 4
    assert count_messages(TiktokenCounter("o200k_base"), messages) == (2 + 4) * 2 + 3


def test_given_oversized_text_when_trimming_then_longest_fitting_head_or_tail_is_kept():
    from app.integrations.tokens import TiktokenCounter, keep_head, keep_tail

    counter = TiktokenCounter("o200k_base")
    text = " word" * 1000
    assert keep_tail(counter, text, 100) == " word" * 100
    assert keep_head(counter, text, 100) == " word" * 100
    assert keep_tail(counter, text, 5000) == text and keep_head(counter, text, 5000) == text
    assert keep_tail(counter, text, 0) == "" and keep_head(counter, text, 0) == ""


def test_given_multibyte_text_when_trimming_then_result_is_valid_and_within_limit():
    from app.integrations.tokens import TiktokenCounter, keep_head, keep_tail

    counter = TiktokenCounter("o200k_base", factor=1.05)
    text = "漢字" * 1600
    head, tail = keep_head(counter, text, 333), keep_tail(counter, text, 333)
    assert text.startswith(head) and text.endswith(tail)
    assert 0 < counter.count(head) <= 333 and 0 < counter.count(tail) <= 333
