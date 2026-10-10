"""Local PDF metadata is a fallback and a set of lookup clues (ARA-086)."""

import pymupdf
import pytest
from support.front_matter import TITLE, toolchain_pdf


def extracted(data: bytes) -> dict:
    from app.jobs.pdf_parser import extract

    with pymupdf.open(stream=data, filetype="pdf") as document:
        return extract(document)["metadata"]


@pytest.mark.parametrize(
    "title",
    [
        "paper.dvi",
        "main.tex",
        "sec18-han.pdf",
        "Microsoft Word - draft.docx",
        "Microsoft PowerPoint - talk",
        "untitled",
        "Untitled-1",
        "Layout 1",
        "Document1",
        "PII: S0004-3702(98)00042-1",
        "C:\\Users\\ada\\Desktop\\final",
        "final_v2",
        "doi:10.1145/3510003.3510047",
        "arXiv:1706.03762v7",
        "   ",
        "ab",
    ],
)
def test_toolchain_and_file_name_titles_are_artifacts(title):
    from app.jobs.pdf_parser import artifact_title

    assert artifact_title(title)


@pytest.mark.parametrize(
    "title",
    [
        TITLE,
        "Attention Is All You Need",
        "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "Exploiting input sanitization for regex denial of service",
    ],
)
def test_real_titles_are_not_artifacts(title):
    from app.jobs.pdf_parser import artifact_title

    assert not artifact_title(title)


def test_toolchain_info_title_yields_to_the_largest_horizontal_first_page_title():
    """Given Info title paper.dvi and a larger rotated margin stamp, the printed title wins."""
    metadata = extracted(toolchain_pdf())
    assert metadata["title"] == TITLE
    assert metadata["arxiv_id"] == "1706.03762"


@pytest.mark.parametrize("info_title", ["Microsoft Word - draft.docx", "untitled", "main.tex"])
def test_other_artifact_titles_never_reach_the_paper(info_title):
    assert extracted(toolchain_pdf(info_title=info_title, stamp=None))["title"] == TITLE


def test_info_title_that_is_not_printed_on_the_first_pages_yields_to_the_printed_title():
    metadata = extracted(toolchain_pdf(info_title="IEEE Transactions on Widget Engineering"))
    assert metadata["title"] == TITLE


def test_a_printed_info_title_is_kept():
    metadata = extracted(toolchain_pdf(info_title=TITLE.upper(), stamp=None))
    assert metadata["title"] == TITLE.upper()


def test_embedded_doi_wins_over_a_reference_doi_and_placeholder_authors_are_dropped():
    metadata = extracted(
        toolchain_pdf(
            subject="Proceedings, doi:10.1145/3510003.3510047",
            info_author="Administrator",
            stamp=None,
        )
    )
    assert metadata["doi"] == "10.1145/3510003.3510047"
    assert metadata["authors"] == []
    assert metadata["arxiv_id"] is None


def test_without_embedded_identifiers_the_first_pages_doi_is_a_clue():
    assert extracted(toolchain_pdf(stamp=None))["doi"] == "10.9999/unrelated.ref"


def test_a_page_set_in_one_size_has_no_printed_title_so_the_info_title_stays():
    """Body text is not a title: a title must be set larger than the page's body text."""
    document = pymupdf.open()
    document.set_metadata({"title": "Original PDF Title"})
    document.new_page().insert_text(
        (72, 72), "Abstract\nGrounded citations refer to physical pages.\nIntroduction\nEvidence."
    )
    data = document.tobytes()
    document.close()
    assert extracted(data)["title"] == "Original PDF Title"


def test_xmp_title_beats_a_printed_info_title_and_supplies_creators_venue_and_year():
    from support.front_matter import AUTHORS, with_xmp, xmp_packet

    data = with_xmp(
        toolchain_pdf(info_title="Module While You Are Sleeping", stamp=None),
        xmp_packet(
            title=TITLE,
            creators=["Seunghun Han", "Wook Shin"],
            venue="27th USENIX Security Symposium",
            cover_date="2018-08-15",
        ),
    )
    metadata = extracted(data)
    assert metadata["title"] == TITLE
    assert metadata["authors"] == ["Seunghun Han", "Wook Shin"]
    assert metadata["venue"] == "27th USENIX Security Symposium"
    # The publication date counts; the file's xmp:CreateDate (2026) never does.
    assert metadata["year"] == 2018
    assert AUTHORS.startswith("Seunghun Han")


def test_xmp_junk_title_is_filtered_like_the_info_title():
    from support.front_matter import with_xmp, xmp_packet

    data = with_xmp(toolchain_pdf(stamp=None), xmp_packet(title="main.tex"))
    assert extracted(data)["title"] == TITLE


@pytest.mark.parametrize(
    "fields", [{"doi": "10.1145/3510003.3510047"}, {"identifier": "doi:10.1145/3510003.3510047"}]
)
def test_xmp_doi_is_the_identifier_clue_before_text_dois(fields):
    from support.front_matter import with_xmp, xmp_packet

    metadata = extracted(with_xmp(toolchain_pdf(stamp=None), xmp_packet(**fields)))
    assert metadata["doi"] == "10.1145/3510003.3510047"


def test_malformed_xmp_never_fails_extraction():
    from support.front_matter import with_xmp

    data = with_xmp(toolchain_pdf(stamp=None), "<x:xmpmeta><rdf:RDF><dc:title>unclosed")
    metadata = extracted(data)
    assert metadata["title"] == TITLE and metadata["venue"] is None
