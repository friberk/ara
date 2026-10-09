"""Short `[S#]` handles become canonical source markers while streaming (ARA-073)."""

from uuid import UUID, uuid5

import pytest

from app.rag.packing import Passage

DOCUMENT = UUID(int=7)


def uid(handle: str) -> UUID:
    return uuid5(DOCUMENT, handle)


def passage(handle: str, *, document=DOCUMENT) -> Passage:
    number = int(handle[1:])
    return Passage(
        handle, uid(handle), document, number, number + 1, "2 Method", "text", f"Text {handle}."
    )


def handle_map(*handles: str):
    from app.rag.citations import HandleMap

    return HandleMap([passage(handle) for handle in handles])


def transducer(*handles: str):
    from app.rag.citations import HandleTransducer

    return HandleTransducer(handle_map(*handles))


def run(t, *deltas: str) -> str:
    return "".join(t.feed(delta) for delta in deltas) + t.flush()


def test_split_marker_across_deltas():
    t = transducer("S12")
    out = t.feed("Recall improves [S1") + t.feed("2] overall.") + t.flush()
    assert out == f"Recall improves [source:{uid('S12')}] overall."


def test_split_marker_is_never_emitted_half_mapped():
    t = transducer("S12")
    first = t.feed("Recall improves [S1")
    assert first == "Recall improves "
    assert t.feed("2") == ""
    assert t.feed("] overall.") == f"[source:{uid('S12')}] overall."


def test_grouped_and_unicode_handles():
    t = transducer("S1", "S3", "S2")
    out = run(t, "A [S1, S3] and B 【S2】.")
    assert out.count("[source:") == 3 and "【" not in out
    assert out == f"A [source:{uid('S1')}][source:{uid('S3')}] and B [source:{uid('S2')}]."


def test_adjacent_and_lowercase_handles():
    t = transducer("S1", "S3")
    out = run(t, "A [s1][S3].")
    assert out == f"A [source:{uid('S1')}][source:{uid('S3')}]."


def test_unknown_handle_recorded():
    t = transducer("S1")
    out = run(t, "Claim [S99].")
    assert t.unknown == {"S99"} and "[source:" not in out


def test_group_with_unknown_handle_is_recorded():
    t = transducer("S1")
    run(t, "Claim [S1, S7].")
    assert t.unknown == {"S7"}


def test_sentinel_removed_and_flagged():
    t = transducer("S1")
    out = t.feed("[insufficient-evidence] The paper does not report latency.") + t.flush()
    assert t.insufficient and out.startswith("The paper")


def test_sentinel_split_across_deltas_is_removed():
    t = transducer("S1")
    out = run(t, "[insufficient-", "evidence]", " The paper is silent.")
    assert t.insufficient and out == "The paper is silent."


def test_without_sentinel_nothing_is_flagged():
    t = transducer("S1")
    run(t, "Supported [S1].")
    assert not t.insufficient and t.unknown == set()


def test_code_block_untouched():
    t = transducer("S1")
    out = t.feed("```\nx = [S1]\n```") + t.flush()
    assert "[S1]" in out and t.unknown == set()


def test_code_fence_split_across_deltas_still_protects_code():
    t = transducer("S1")
    out = run(t, "Before [S1].\n``", "`\ny = [S1]\n`", "``\nAfter [S1].")
    marker = f"[source:{uid('S1')}]"
    assert out == f"Before {marker}.\n```\ny = [S1]\n```\nAfter {marker}."


def test_ordinary_brackets_pass_through_without_delay():
    t = transducer("S1")
    assert t.feed("See [Table 1] and [a") == "See [Table 1] and [a"
    assert t.flush() == ""


def test_long_unterminated_bracket_is_released():
    t = transducer("S1")
    assert t.feed("[S1, S1, S1, S1, S1, S1, S1, S1, S1, S1, S1, S1, S1") != ""


def test_unterminated_tail_is_emitted_on_flush():
    t = transducer("S1")
    assert run(t, "Cut off [S") == "Cut off [S"


def test_existing_source_markers_pass_through():
    t = transducer("S1")
    marker = f"[source:{uid('S1')}]"
    assert run(t, f"Already canonical {marker}.") == f"Already canonical {marker}."


def test_handle_map_resolves_case_and_leading_zeros():
    handles = handle_map("S1", "S12")
    assert handles.resolve("s12").chunk_id == uid("S12")
    assert handles.resolve("S01").chunk_id == uid("S1")
    assert handles.resolve("S2") is None


def test_insufficient_sentinel_has_one_definition():
    from app.rag import citations
    from app.services import context

    assert citations.INSUFFICIENT == "[insufficient-evidence]"
    assert context.INSUFFICIENT is citations.INSUFFICIENT


def test_given_mapped_answer_when_citing_then_passages_give_full_provenance():
    from app.rag.citations import passage_citations

    passages = [passage("S1"), passage("S2")]
    passages[1] = Passage(**{**vars(passages[1]), "bboxes": [[3, 1.0, 2.0, 3.0, 4.0]]})
    content = f"A [source:{uid('S2')}] b 【source:{uid('S1')}】 c [source:{uid('S2')}]."
    cited = passage_citations(content, passages, DOCUMENT)
    assert [c.chunk_id for c in cited] == [uid("S2"), uid("S1")]
    assert cited[0].model_dump() == {
        "chunk_id": uid("S2"),
        "document_id": DOCUMENT,
        "page": 2,
        "page_end": 3,
        "section": "2 Method",
        "kind": "text",
        "bboxes": [[3, 1.0, 2.0, 3.0, 4.0]],
        "excerpt": "Text S2.",
    }


@pytest.mark.parametrize("kind", ["unknown", "foreign", "malformed"])
def test_given_unsupplied_source_when_citing_then_it_is_rejected(kind):
    from app.rag.citations import passage_citations

    foreign = passage("S2", document=UUID(int=8))
    marker = {
        "unknown": f"[source:{UUID(int=5)}]",
        "foreign": f"[source:{foreign.chunk_id}]",
        "malformed": "【source:not-a-uuid】",
    }[kind]
    with pytest.raises(ValueError):
        passage_citations(f"Claim {marker}.", [passage("S1"), foreign], DOCUMENT)
