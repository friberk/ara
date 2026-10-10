"""Generate a small explicitly synthetic PDF used in deterministic browser tests."""

from pathlib import Path
import pymupdf


def create_pdf(destination):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "Traceable Research Systems",
            "author": "Ada Researcher",
            "subject": "Synthetic test document",
        }
    )
    pages = [
        "Traceable Research Systems\nAda Researcher\n2024\n\nAbstract\nA synthetic evaluation of a retrieval-first research assistant using the Orion-12 dataset.\n\nIntroduction\nThis synthetic research fixture studies how page-aware retrieval helps a user verify generated answers.",
        "Methodology\nThe method first extracts page text, then retrieves relevant chunks and generates answers grounded in those passages.\n\nDatasets\nThe experiment uses the Orion-12 dataset, which contains twelve synthetic question and answer examples.\n\nResults\nThe measured answer accuracy in this synthetic experiment is 86 percent.",
        "Limitations\nThe small synthetic dataset contains only twelve examples and does not establish performance on real research libraries.\n\nConclusion\nSource citations make the output easier to inspect. This is a synthetic test fixture rather than a published research claim.",
    ]
    for text in pages:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 790), text, fontsize=12)
    document.save(path)
    document.close()
    return path


def create_second_pdf(destination):
    """A second synthetic paper with its own embedded title and author, so an upload becomes
    its own library paper (ARA-088's multi-paper journey)."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "Sparse Indexes for Lab Notebooks",
            "author": "Ben Analyst",
            "subject": "Synthetic test document",
        }
    )
    pages = [
        "Sparse Indexes for Lab Notebooks\nBen Analyst\n2023\n\nAbstract\nA synthetic study of keyword indexes over lab notebooks using the Vega-7 dataset.",
        "Datasets\nThe experiment uses the Vega-7 dataset, which contains seven synthetic notebook questions.\n\nResults\nThe measured answer accuracy in this synthetic experiment is 74 percent.",
    ]
    for text in pages:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 790), text, fontsize=12)
    document.save(path)
    document.close()
    return path


if __name__ == "__main__":
    import sys

    arguments = sys.argv[1:]
    if arguments[:1] == ["--second"]:
        print(create_second_pdf(arguments[1] if len(arguments) > 1 else "/tmp/ara-fixtures/second.pdf"))
    else:
        print(create_pdf(arguments[0] if arguments else "/tmp/ara-fixtures/research.pdf"))
