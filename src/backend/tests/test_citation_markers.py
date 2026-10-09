"""ARA-052 Unicode source-marker cases, run against the ARA-073 passage validator."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from support.citations import validate_citations

DOCUMENT = UUID("a4a44444-4444-4444-8444-444444444444")
SOURCE_ID = UUID("a1a11111-1111-4111-8111-111111111111")
FOREIGN_ID = UUID("a2a22222-2222-4222-8222-222222222222")
UNKNOWN_ID = UUID("a3a33333-3333-4333-8333-333333333333")


def evidence():
    return [SimpleNamespace(id=SOURCE_ID, document_id=DOCUMENT, page=2, text="Twelve examples.")]


@pytest.mark.parametrize("wrapper", ["[source:{}]", "【source:{}】"])
def test_given_known_marker_when_validating_then_citation_keeps_document_and_page(wrapper):
    citations = validate_citations(
        "Twelve examples " + wrapper.format(SOURCE_ID), evidence(), DOCUMENT
    )
    assert [(item.chunk_id, item.document_id, item.page) for item in citations] == [
        (SOURCE_ID, DOCUMENT, 2)
    ]


def test_given_both_wrappers_for_same_source_when_validating_then_no_duplicate_citation():
    citations = validate_citations(
        f"One [source:{SOURCE_ID}] and two 【source:{SOURCE_ID}】", evidence(), DOCUMENT
    )
    assert [item.chunk_id for item in citations] == [SOURCE_ID]


@pytest.mark.parametrize("unavailable", [UNKNOWN_ID, FOREIGN_ID])
def test_given_unknown_or_foreign_unicode_source_alongside_known_when_validating_then_reject(
    unavailable,
):
    chunks = [
        *evidence(),
        SimpleNamespace(id=FOREIGN_ID, document_id=UUID(int=0), page=9, text="Another document."),
    ]
    with pytest.raises(ValueError, match="outside"):
        validate_citations(
            f"Known [source:{SOURCE_ID}] and unsupported 【source:{unavailable}】", chunks, DOCUMENT
        )


@pytest.mark.parametrize(
    "marker",
    [
        "【source:not-a-uuid】",
        "【source:】",
        f"【source:{SOURCE_ID}]malformed】",
        f"【source:[source:{SOURCE_ID}]】",
        f"【source:{SOURCE_ID}【nested】】",
        f"【source: {SOURCE_ID}】",
        f"【source:{SOURCE_ID} 】",
        "【source:1】",
    ],
)
def test_given_malformed_closed_unicode_marker_alongside_valid_when_validating_then_reject(marker):
    with pytest.raises(ValueError):
        validate_citations(f"Known [source:{SOURCE_ID}] and bad {marker}", evidence(), DOCUMENT)


@pytest.mark.parametrize(
    "marker", [f"【source:{SOURCE_ID}", f"【SOURCE:{SOURCE_ID}】", f"（source:{SOURCE_ID}）"]
)
def test_given_unrecognized_or_unclosed_wrapper_when_validating_then_no_false_citation(marker):
    assert validate_citations(marker, evidence(), DOCUMENT) == []


@pytest.mark.parametrize(
    "marker", [f"[source:{str(SOURCE_ID).upper()}]", f"【source:{str(SOURCE_ID).upper()}】"]
)
def test_given_uppercase_id_when_validating_then_existing_exact_membership_is_preserved(marker):
    with pytest.raises(ValueError, match="outside"):
        validate_citations(marker, evidence(), DOCUMENT)
