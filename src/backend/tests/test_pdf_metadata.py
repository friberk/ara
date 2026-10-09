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
