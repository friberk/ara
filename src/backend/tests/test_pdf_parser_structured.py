"""The isolated child parses PDFs with PyMuPDF4LLM layout Markdown (ARA-071)."""

import asyncio

from support.structured_pdf import create_structured_pdf

TUNING = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MALLOC_ARENA_MAX": "2"}


def assert_boxes_tile(page):
    spans = sorted((box["start"], box["end"]) for box in page["boxes"])
    assert spans[0][0] == 0 and spans[-1][1] == len(page["markdown"])
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:], strict=False))


def formula_pdf(path, formula="Attention(Q, K, V) = softmax("):
    """One page of prose around a typeset display equation, which layout classifies as formula."""
    import pymupdf

    body = (
        "We compute the attention function on a set of queries simultaneously, packed into a "
        "matrix Q. The keys and values are packed into matrices K and V. We compute the matrix "
        "of outputs as: "
    ) * 2
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(72, 100, 540, 200), body, fontsize=10, fontname="tiro")
    page.insert_text((200, 230), formula, fontsize=10, fontname="tiit")
    page.insert_text((340, 222), "QK", fontsize=10, fontname="tiit")
    page.insert_text((356, 218), "T", fontsize=7, fontname="tiit")
    page.draw_line((335, 226), (380, 226), width=0.5)
    page.insert_text((345, 238), "√d", fontsize=10, fontname="symb")
    page.insert_text((362, 240), "k", fontsize=7, fontname="tiit")
    page.insert_text((385, 230), ")V", fontsize=10, fontname="tiit")
    page.insert_text((520, 230), "(1)", fontsize=10, fontname="tiro")
    page.insert_textbox(pymupdf.Rect(72, 260, 540, 400), body, fontsize=10, fontname="tiro")
    document.save(path)
    document.close()
    return path


async def test_given_structured_pdf_when_parsed_then_layout_markdown_has_headings_table_boxes(
    tmp_path,
):
    from app.services.ingestion import parse_in_child

    pdf = create_structured_pdf(tmp_path / "s.pdf")
    parsed = await parse_in_child(pdf.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-layout"
    assert parsed["extractor_version"] == "pymupdf4llm-1.28.2+layout"
    pages = parsed["pages"]
    assert [p["page"] for p in pages] == [1, 2, 3, 4]
    assert all(p["text"].strip() for p in pages)  # plain text is kept for DocumentPage rows
    joined = "\n".join(p["markdown"] for p in pages).replace("**", "")
    assert "# " in joined and "2 Method" in joined and "References" in joined
    assert "|Model|Recall@10|Latency(ms)|" in joined.replace(" ", "")
    for page in pages:
        assert_boxes_tile(page)
    assert any(b["class"] == "section-header" for p in pages for b in p["boxes"])
    table = next(b for b in pages[2]["boxes"] if b["class"] == "table")
    assert "Recall@10" in pages[2]["markdown"][table["start"] : table["end"]]
    assert len(table["bbox"]) == 4


async def test_given_layout_failure_when_parsed_then_legacy_fallback(tmp_path, monkeypatch):
    from app.services.ingestion import parse_in_child

    pdf = create_structured_pdf(tmp_path / "s.pdf")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ARA_PARSER_FORCE_LAYOUT_ERROR", "1")
    parsed = await parse_in_child(pdf.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-legacy" and parsed["pages"][0]["boxes"] == []
    assert parsed["extractor_version"] == "pymupdf4llm-1.28.2+legacy"
    assert "2 Method" in "\n".join(p["markdown"] for p in parsed["pages"])


async def test_given_forced_layout_error_outside_tests_then_hook_is_ignored(tmp_path, monkeypatch):
    from app.services.ingestion import parse_in_child

    pdf = create_structured_pdf(tmp_path / "s.pdf")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ARA_PARSER_FORCE_LAYOUT_ERROR", "1")
    parsed = await parse_in_child(pdf.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-layout"


async def test_given_image_only_pdf_then_ocr_required(tmp_path):
    import pymupdf

    from app.services.ingestion import parse_in_child

    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), 0)
    page.insert_image(pymupdf.Rect(50, 50, 300, 300), pixmap=pixmap)
    path = tmp_path / "image.pdf"
    document.save(path)
    parsed = await parse_in_child(path.read_bytes())
    assert parsed["error"]["code"] == "OCR_REQUIRED"


async def test_given_text_and_scanned_pages_when_parsed_then_layout_ocr_stays_disabled(tmp_path):
    """Layout OCR would read the rendered words (or fail without Tesseract data)."""
    import pymupdf

    from app.services.ingestion import parse_in_child

    rendered = pymupdf.open()
    rendered.new_page().insert_text((72, 72), "Rendered words for OCR", fontsize=24)
    pixmap = rendered[0].get_pixmap(dpi=150)
    document = pymupdf.open()
    document.new_page().insert_textbox(
        pymupdf.Rect(72, 200, 540, 400),
        "A text page about retrieval with enough prose to form a paragraph. " * 4,
        fontsize=10,
    )
    scanned = document.new_page()
    scanned.insert_image(scanned.rect, pixmap=pixmap)
    path = tmp_path / "mixed.pdf"
    document.save(path)
    parsed = await parse_in_child(path.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-layout"
    assert "Rendered" not in parsed["pages"][1]["markdown"]
    assert parsed["warnings"] == ["Some pages contain no extractable text."]


async def test_given_display_formula_when_parsed_then_clipped_text_fills_formula_box(tmp_path):
    from app.services.ingestion import parse_in_child

    parsed = await parse_in_child(formula_pdf(tmp_path / "formula.pdf").read_bytes())
    page = parsed["pages"][0]
    formula = next(b for b in page["boxes"] if b["class"] == "formula")
    filled = page["markdown"][formula["start"] : formula["end"]]
    assert filled.strip().startswith("$$") and filled.strip().endswith("$$")
    assert "Attention(Q, K, V)" in filled
    assert_boxes_tile(page)


async def test_given_page_whose_only_text_layout_drops_then_plain_text_is_kept(tmp_path):
    """Layout treats a lone top line as a page header; header=False would leave no Markdown."""
    import pymupdf

    from app.services.ingestion import parse_in_child

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Results\nThe experiment obtained 87 percent.")
    path = tmp_path / "short.pdf"
    document.save(path)
    parsed = await parse_in_child(path.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-layout"
    assert "87 percent" in parsed["pages"][0]["markdown"]


def test_fill_formulas_inserts_clipped_text_and_shifts_later_boxes():
    from app.jobs.pdf_parser import fill_formulas

    markdown = "Intro text. \n\n\n\nAfter text. \n\n"
    boxes = [
        {"class": "text", "bbox": [0, 0, 1, 1], "start": 0, "end": 14},
        {"class": "formula", "bbox": [0, 2, 1, 3], "start": 14, "end": 16},
        {"class": "formula", "bbox": [0, 4, 1, 5], "start": 16, "end": 16},
        {"class": "text", "bbox": [0, 6, 1, 7], "start": 16, "end": 30},
    ]
    clipped = {(0, 2, 1, 3): " a = b\n + c \n", (0, 4, 1, 5): "  "}
    filled, shifted = fill_formulas(markdown, boxes, lambda bbox: clipped[tuple(bbox)])
    assert filled == "Intro text. \n\n\n\n$$ a = b + c $$\n\nAfter text. \n\n"
    formula = shifted[1]
    assert filled[formula["start"] : formula["end"]] == "\n\n$$ a = b + c $$\n\n"
    assert shifted[2]["start"] == shifted[2]["end"] == formula["end"]
    assert filled[shifted[3]["start"] : shifted[3]["end"]] == "After text. \n\n"


async def test_given_parse_when_child_runs_then_it_fits_tuned_limits(tmp_path):
    """A 40-page paper parses in layout mode under RLIMIT_AS 1.5 GiB within the deadline."""
    import pymupdf

    from app.services.ingestion import parse_in_child

    fixture = pymupdf.open(create_structured_pdf(tmp_path / "s.pdf"))
    document = pymupdf.open()
    for _ in range(10):
        document.insert_pdf(fixture)
    path = tmp_path / "forty.pdf"
    document.save(path)
    parsed = await parse_in_child(path.read_bytes())
    assert "error" not in parsed
    assert parsed["parser"] == "pymupdf4llm-layout" and len(parsed["pages"]) == 40


async def test_given_concurrent_parses_then_one_child_runs_at_a_time(tmp_path, monkeypatch):
    from app.services import ingestion

    alive, peak = 0, 0
    real = asyncio.create_subprocess_exec

    async def counting(*args, **kwargs):
        nonlocal alive, peak
        process = await real(*args, **kwargs)
        alive += 1
        peak = max(peak, alive)
        wait = process.wait

        async def finished():
            nonlocal alive
            code = await wait()
            alive -= 1
            process.wait = wait
            return code

        process.wait = finished
        return process

    monkeypatch.setattr(ingestion.asyncio, "create_subprocess_exec", counting)
    data = create_structured_pdf(tmp_path / "s.pdf").read_bytes()
    results = await asyncio.gather(*(ingestion.parse_in_child(data) for _ in range(2)))
    assert [r["parser"] for r in results] == ["pymupdf4llm-layout"] * 2
    assert peak == 1


def test_parser_environment_tunes_threads_and_scrubs_secrets(monkeypatch):
    from app.services.ingestion import parser_environment

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ARA_PARSER_FORCE_LAYOUT_ERROR", "1")
    environment = parser_environment()
    assert {key: environment[key] for key in TUNING} == TUNING
    assert not {"OPENAI_API_KEY", "APP_ENV", "ARA_PARSER_FORCE_LAYOUT_ERROR"} & set(environment)



async def test_given_control_characters_in_a_formula_then_parsed_strings_are_storable(tmp_path):
    """TeX math-extension fonts encode big parentheses at code points 0 and 1 (RAG, 2005.11401).

    Formula filling copies clipped PDF text, and PostgreSQL text rejects NUL. Control characters
    become U+FFFD, as layout Markdown already renders them in body text, so offsets keep.
    """
    import re

    from app.services.ingestion import parse_in_child

    path = formula_pdf(tmp_path / "control.pdf", formula="Attention(Q, K, V) = softmax\x00(")
    page = (await parse_in_child(path.read_bytes()))["pages"][0]
    control = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    assert not control.search(page["text"]) and not control.search(page["markdown"])
    formula = next(b for b in page["boxes"] if b["class"] == "formula")
    assert "softmax\ufffd" in page["markdown"][formula["start"] : formula["end"]]
    assert_boxes_tile(page)
