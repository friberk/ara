"""Section-aware chunk plans from layout Markdown with LlamaIndex parsers (ARA-071)."""

PAGES = [
    {
        "page": 1,
        "markdown": "# **Sparse Retrieval**\n\n## Abstract\n\nWe study sparse retrieval.\n\n",
        "boxes": [],
    },
    {
        "page": 2,
        "markdown": "## **2 Method**\n\n### 2.1 Indexing\n\nWe index passages with BM25 and",
        "boxes": [],
    },
    {
        "page": 3,
        "markdown": "continue with dense vectors.\n\n## 3 Results\n\n"
        "|Model|Recall@10|\n|---|---|\n|BM25|0.61|\n\n",
        "boxes": [{"class": "table", "bbox": [72, 300, 540, 360], "start": 50, "end": 100}],
    },
    {"page": 4, "markdown": "## References\n\n- [1] Robertson. BM25.", "boxes": []},
]


def test_continuation_keeps_full_heading_stack_across_pages():
    from app.rag.chunking import build_chunk_plan

    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    cont = next(c for c in plan.chunks if "continue with dense" in c.text)
    assert cont.section_path[-2:] == ["2 Method", "2.1 Indexing"]
    assert cont.page == 2 and cont.page_end == 3


def test_headings_are_clean_and_heading_only_nodes_merge():
    from app.rag.chunking import build_chunk_plan

    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    assert all("**" not in s.title and "#" not in s.title for s in plan.sections)
    assert not any(c.text.strip() in {"## **2 Method**", "## 2 Method"} for c in plan.chunks)
    merged = next(c for c in plan.chunks if "2.1 Indexing" in c.text)
    assert merged.text.startswith("## **2 Method**")
    method = next(s for s in plan.sections if s.title == "2 Method")
    assert method.level == 2 and method.page == 2 and method.role == "body"


def test_table_kind_with_box_and_references_excluded_role():
    from app.rag.chunking import build_chunk_plan

    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    table = next(c for c in plan.chunks if c.kind == "table")
    assert "Recall@10" in table.text and table.bboxes and table.bboxes[0][0] == 3
    assert table.bboxes[0][1:] == [72, 300, 540, 360]
    assert any(s.role == "references" for s in plan.sections)
    assert any(c.kind == "references" for c in plan.chunks)


def test_context_text_prefixes_title_and_heading():
    from app.rag.chunking import build_chunk_plan

    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    chunk = next(c for c in plan.chunks if "BM25 and" in c.text)
    lines = chunk.context_text.splitlines()
    assert lines[0] == "Sparse Retrieval" and lines[1].endswith("2 Method > 2.1 Indexing")
    assert chunk.heading == " > ".join(chunk.section_path)


def test_sections_and_chunks_follow_reading_order():
    from app.rag.chunking import CHUNK_SET, build_chunk_plan

    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    assert plan.chunk_set == CHUNK_SET
    assert [c.ordinal for c in plan.chunks] == list(range(len(plan.chunks)))
    assert [s.ordinal for s in plan.sections] == list(range(len(plan.sections)))
    assert [s.title for s in plan.sections] == [
        "Sparse Retrieval",
        "Abstract",
        "2 Method",
        "2.1 Indexing",
        "3 Results",
        "References",
    ]
    by_ordinal = {s.ordinal: s for s in plan.sections}
    for chunk in plan.chunks:
        assert by_ordinal[chunk.section_ordinal].path == chunk.section_path
    assert [c.page for c in plan.chunks] == sorted(c.page for c in plan.chunks)


def test_no_headings_still_chunks_within_budget():
    from app.rag.chunking import build_chunk_plan

    plan = build_chunk_plan([{"page": 1, "markdown": "plain text " * 400, "boxes": []}], title=None)
    assert plan.chunks and all(c.context_text and c.section_path == [] for c in plan.chunks)
    assert max(c.token_count for c in plan.chunks) <= 512
    assert {c.kind for c in plan.chunks} == {"text"} and plan.sections == []


def test_no_headings_report_gets_page_level_chunks():
    """Review focus 2: a plain multi-page report still yields chunks on every page."""
    from app.rag.chunking import build_chunk_plan

    pages = [
        {"page": n, "markdown": f"Page {n} findings. " + "Observation. " * 300, "boxes": []}
        for n in (1, 2, 3)
    ]
    plan = build_chunk_plan(pages, title="Plain Report")
    assert {c.page for c in plan.chunks} == {1, 2, 3}
    assert all(c.context_text.startswith("Plain Report\n") for c in plan.chunks)
    first_on_page_two = next(c for c in plan.chunks if "Page 2 findings" in c.text)
    assert first_on_page_two.page_end >= 2


def test_long_section_respects_token_budget():
    from app.rag.chunking import build_chunk_plan

    markdown = "## Intro\n\n" + ("Sentence about retrieval. " * 600)
    long = [{"page": 1, "markdown": markdown, "boxes": []}]
    plan = build_chunk_plan(long, title="T")
    assert all(c.token_count <= 512 for c in plan.chunks) and len(plan.chunks) > 3
    assert all(c.section_path == ["Intro"] for c in plan.chunks)


def test_front_matter_before_first_heading():
    from app.rag.chunking import build_chunk_plan

    markdown = "Preprint. Under review.\n\n## Abstract\n\nBody."
    plan = build_chunk_plan([{"page": 1, "markdown": markdown, "boxes": []}], title="Paper")
    first = plan.chunks[0]
    assert "Preprint" in first.text and first.kind == "front_matter"
    assert first.section_ordinal is None
    assert plan.chunks[-1].kind == "text"


def test_heading_with_slash_stays_one_segment():
    from app.rag.chunking import build_chunk_plan

    pages = [
        {
            "page": 1,
            "markdown": "## 4 Input/Output Format\n\n### _Token_ <sup>1</sup> Limits\n\nText.",
            "boxes": [],
        }
    ]
    plan = build_chunk_plan(pages, title=None)
    assert plan.chunks[-1].section_path == ["4 Input/Output Format", "Token Limits"]


def test_bboxes_skip_page_furniture_and_follow_chunk_pages():
    from app.rag.chunking import build_chunk_plan

    markdown = "## Intro\n\nBody text here.\n\n"
    pages = [
        {
            "page": 1,
            "markdown": markdown,
            "boxes": [
                {"class": "page-header", "bbox": [0, 0, 10, 10], "start": 0, "end": 0},
                {"class": "section-header", "bbox": [72, 80, 200, 95], "start": 0, "end": 10},
                {"class": "picture", "bbox": [72, 100, 300, 300], "start": 10, "end": 10},
                {"class": "text", "bbox": [72, 300, 540, 320], "start": 10, "end": len(markdown)},
            ],
        }
    ]
    chunk = build_chunk_plan(pages, title=None).chunks[0]
    assert chunk.bboxes == [[1, 72, 80, 200, 95], [1, 72, 300, 540, 320]]


def test_token_counts_use_the_supplied_counter():
    from app.rag.chunking import build_chunk_plan

    class Words:
        def count(self, text: str) -> int:
            return len(text.split())

    plan = build_chunk_plan(PAGES, title="Sparse Retrieval", counter=Words())
    assert all(c.token_count == len(c.text.split()) for c in plan.chunks)


def test_section_page_range_covers_its_subsections():
    from app.rag.chunking import build_chunk_plan

    sections = {s.title: s for s in build_chunk_plan(PAGES, title="Sparse Retrieval").sections}
    assert (sections["2 Method"].page, sections["2 Method"].page_end) == (2, 3)
    assert (sections["Sparse Retrieval"].page, sections["Sparse Retrieval"].page_end) == (1, 4)
    assert sections["Sparse Retrieval"].role == "front_matter"


def test_special_token_text_in_a_paper_does_not_break_chunking():
    # LLM papers quote tokenizer markers; tiktoken raises on them unless special tokens are allowed.
    pages = [
        {
            "page": 1,
            "markdown": "## Method\n\nSequences end with <|endoftext|> and <|im_start|>. "
            + ("Training continues for many steps. " * 300),
            "boxes": [],
        }
    ]
    from app.rag.chunking import build_chunk_plan

    plan = build_chunk_plan(pages, title="Tokenizers")
    assert plan.chunks and any("<|endoftext|>" in c.text for c in plan.chunks)
    assert all(c.token_count <= 512 for c in plan.chunks)


def test_default_counter_is_the_shared_o200k_counter():
    from app.integrations.tokens import TiktokenCounter
    from app.rag.chunking import default_counter

    counter = default_counter()
    assert isinstance(counter, TiktokenCounter) and counter.factor == 1.0
