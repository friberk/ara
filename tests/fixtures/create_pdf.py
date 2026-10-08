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


if __name__ == "__main__":
    import sys

    print(
        create_pdf(
            sys.argv[1] if len(sys.argv) > 1 else "/tmp/ara-fixtures/research.pdf"
        )
    )
