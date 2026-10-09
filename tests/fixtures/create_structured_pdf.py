"""Generate a synthetic four-page paper with real structure for retrieval tests (ARA-070).

Page 1: title, authors, Abstract. Page 2: 1 Introduction, 2 Method (continues on page 3).
Page 3: Method continuation without a heading, then 3 Results with a ruled 3x3 table.
Page 4: References. Headings are 14 pt bold; body text is 10 pt.
Run: uv run --with pymupdf==1.28.2 python tests/fixtures/create_structured_pdf.py OUT.pdf
"""

from pathlib import Path
import sys

import pymupdf

TITLE = "Sparse Retrieval for Scientific QA"
LEFT, RIGHT, WIDTH = 72, 540, 468


class Writer:
    def __init__(self, document):
        self.document = document
        self.page = None
        self.y = 0.0

    def new_page(self):
        self.page = self.document.new_page(width=612, height=792)
        self.y = 72.0

    def heading(self, text, size=14):
        self.y += 8
        self.page.insert_text((LEFT, self.y + size), text, fontsize=size, fontname="hebo")
        self.y += size + 10

    def paragraph(self, text, size=10):
        rect = pymupdf.Rect(LEFT, self.y, RIGHT, self.y + 400)
        unused = self.page.insert_textbox(rect, text, fontsize=size, fontname="helv")
        self.y += 400 - unused + 8

    def table(self, rows):
        columns = len(rows[0])
        cell_width, cell_height = WIDTH / columns, 20
        top = self.y
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                x0, y0 = LEFT + c * cell_width, top + r * cell_height
                self.page.draw_rect(pymupdf.Rect(x0, y0, x0 + cell_width, y0 + cell_height), width=0.8)
                font = "hebo" if r == 0 else "helv"
                self.page.insert_text((x0 + 4, y0 + 14), value, fontsize=10, fontname=font)
        self.y = top + len(rows) * cell_height + 12


def create_structured_pdf(destination):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    document.set_metadata({"title": TITLE, "author": "Ada Researcher; Ben Analyst"})
    writer = Writer(document)

    writer.new_page()
    writer.heading(TITLE, size=20)
    writer.paragraph("Ada Researcher and Ben Analyst. Synthetic Institute of Retrieval.")
    writer.heading("Abstract")
    writer.paragraph(
        "We study sparse retrieval for question answering over scientific papers. A lexical "
        "BM25 index is compared with dense vectors on a synthetic benchmark of 120 questions."
    )

    writer.new_page()
    writer.heading("1 Introduction")
    writer.paragraph(
        "Researchers ask precise questions about datasets, baselines and limitations. Retrieval "
        "must find the passage that answers each question before a model writes an answer."
    )
    writer.heading("2 Method")
    writer.paragraph(
        "We index every passage with BM25 using the Okapi weighting and a stemmed English "
        "vocabulary. Passages are split at section boundaries and capped at 512 tokens. The "
        "dense baseline encodes the same passages with a bi-encoder trained on scientific text."
    )

    writer.new_page()
    writer.paragraph(
        "The method section continues on this page: both indexes share identical passages, so "
        "differences in recall come only from the ranking function and not from chunking."
    )
    writer.heading("3 Results")
    writer.paragraph("Table 1 reports recall at ten retrieved passages and median latency.")
    writer.table(
        [
            ["Model", "Recall@10", "Latency (ms)"],
            ["BM25", "0.61", "4"],
            ["Dense", "0.72", "19"],
        ]
    )
    writer.paragraph("Dense retrieval improves recall while BM25 remains five times faster.")

    writer.new_page()
    writer.heading("References")
    writer.paragraph(
        "[1] S. Robertson and H. Zaragoza. The probabilistic relevance framework: BM25 and beyond.\n"
        "[2] V. Karpukhin et al. Dense passage retrieval for open-domain question answering.\n"
        "[3] P. Lewis et al. Retrieval-augmented generation for knowledge-intensive NLP tasks."
    )
    document.save(path)
    document.close()
    return path


if __name__ == "__main__":
    print(create_structured_pdf(sys.argv[1]))
