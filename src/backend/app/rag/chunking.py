"""Section-aware chunk plans from PyMuPDF4LLM page Markdown with LlamaIndex parsers (ARA-071).

LlamaIndex does the parsing: `MarkdownNodeParser` builds sections and `SentenceSplitter` caps
them by tokens. Our glue only locates nodes in the whole-paper text, folds heading-only nodes
into the node that follows them, and maps chunk ranges back to pages and layout boxes.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol

from app.integrations.tokens import TiktokenCounter

CHUNK_SET = "pymupdf4llm-1.28.2-layout:md-sentence-512-64:v1"  # bump on any parameter change

# Unit separator: unlike "/", it never appears in a heading.
PATH_SEPARATOR = "\x1f"
HEADING = re.compile(r"^(#+)\s(.*)")
REFERENCES = re.compile(r"(?i)^(\d+\.?\s*)?(references|bibliography|works cited)$")
TABLE_ROW = re.compile(r"^\|.*\|\s*$", re.M)
EMPHASIS = re.compile(r"(?<![\w*])[*_]([^*_]+)[*_](?![\w*])")
FURNITURE = {"page-header", "page-footer", "picture"}


class TokenCount(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class SectionDraft:
    ordinal: int
    title: str
    level: int
    path: list[str]
    role: str
    page: int
    page_end: int


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    section_ordinal: int | None
    section_path: list[str]
    heading: str
    kind: str
    page: int
    page_end: int
    bboxes: list[list[float]]
    text: str
    context_text: str
    token_count: int


@dataclass(frozen=True)
class ChunkPlan:
    chunk_set: str
    sections: list[SectionDraft]
    chunks: list[ChunkDraft]


@cache
def default_counter() -> TiktokenCounter:
    """The shared o200k counter; it treats special-token text in papers as ordinary text."""
    return TiktokenCounter("o200k_base")


def encode(text: str) -> list[int]:
    return default_counter().encoding.encode(text, disallowed_special=())


def clean_heading(segment: str) -> str:
    segment = re.sub(r"<sup>.*?</sup>", " ", segment)
    segment = segment.replace("**", "").replace("__", "")
    segment = EMPHASIS.sub(r"\1", segment)
    return " ".join(segment.strip("#*_ \t").split())


def heading_only(text: str) -> bool:
    text = text.strip()
    return "\n" not in text and HEADING.match(text) is not None


@cache
def section_annotator():
    """The LlamaIndex transform between the two parsers; built lazily to keep imports cheap."""
    from llama_index.core.schema import TextNode, TransformComponent

    class SectionAnnotator(TransformComponent):
        """Record each node's section path and offset; fold heading-only nodes forward."""

        text: str

        def __call__(self, nodes, **kwargs: Any):
            annotated, folded, cursor = [], [], 0
            for node in nodes:
                found = self.text.find(node.text, cursor)
                start = found if found >= 0 else cursor
                end = start + len(node.text)
                cursor = end if found >= 0 else cursor
                parents = node.metadata.get("header_path", "").split(PATH_SEPARATOR)
                path = [title for title in map(clean_heading, parents) if title]
                level = None
                own = HEADING.match(node.text.strip().split("\n", 1)[0])
                if own and clean_heading(own[2]):
                    path.append(clean_heading(own[2]))
                    level = len(own[1])
                section = {"path": path, "level": level, "start": start}
                if heading_only(node.text):
                    folded.append(section)
                    continue
                annotated.append(self.node(start, end, section, folded))
                folded = []
            if folded:  # The paper ends with headings and no text below them.
                last = folded.pop()
                annotated.append(self.node(last["start"], len(self.text), last, folded))
            return annotated

        def node(self, start, end, section, folded):
            begin = folded[0]["start"] if folded else start
            metadata = {**section, "start": begin, "folded": folded}
            return TextNode(
                text=self.text[begin:end],
                metadata=metadata,
                excluded_embed_metadata_keys=list(metadata),
                excluded_llm_metadata_keys=list(metadata),
            )

    return SectionAnnotator


def build_chunk_plan(
    pages: list[dict],
    *,
    title: str | None,
    chunk_tokens: int = 512,
    overlap_tokens: int = 64,
    counter: TokenCount | None = None,
) -> ChunkPlan:
    from llama_index.core import Document
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter

    counter = counter or default_counter()
    # One whole-paper Document without metadata keeps the heading stack across page breaks.
    page_starts, parts, offset = [], [], 0
    for page in pages:
        page_starts.append(offset)
        parts.append(page["markdown"])
        offset += len(page["markdown"]) + 2
    text = "\n\n".join(parts)
    pipeline = IngestionPipeline(
        transformations=[
            MarkdownNodeParser(header_path_separator=PATH_SEPARATOR),
            section_annotator()(text=text),
            SentenceSplitter(
                chunk_size=chunk_tokens,
                chunk_overlap=overlap_tokens,
                tokenizer=encode,
            ),
        ],
        disable_cache=True,
    )
    nodes = pipeline.run(documents=[Document(text=text)])

    def page_at(position: int) -> int:
        return pages[max(0, bisect_right(page_starts, position) - 1)]["page"]

    def boxes_between(start: int, end: int) -> list[list[float]]:
        found = []
        for page_start, page in zip(page_starts, pages, strict=True):
            for box in page.get("boxes", []):
                if box["class"] in FURNITURE:
                    continue
                if page_start + box["start"] < end and page_start + box["end"] > start:
                    found.append([page["page"], *box["bbox"]])
        return found

    has_headings = any(n.metadata["path"] or n.metadata["folded"] for n in nodes)
    first_heading = next(
        (s["path"] for n in nodes for s in [*n.metadata["folded"], n.metadata] if s["path"]), []
    )
    title_path = (
        first_heading
        if title and first_heading[:1] == [clean_heading(title)] and len(first_heading) == 1
        else None
    )

    def role(path: list[str]) -> str:
        if any(REFERENCES.match(segment) for segment in path):
            return "references"
        return "front_matter" if path == title_path or not path else "body"

    sections: dict[tuple[str, ...], dict] = {}

    def visit(section: dict, page: int, page_end: int) -> int | None:
        path = section["path"]
        if not path:
            return None
        entry = sections.setdefault(
            tuple(path),
            {
                "ordinal": len(sections),
                "level": section["level"] or len(path),
                "page": page,
                "page_end": page_end,
            },
        )
        entry["page_end"] = max(entry["page_end"], page_end)
        return entry["ordinal"]

    chunks, previous_start = [], -1
    for node in nodes:
        metadata = node.metadata
        found = text.find(node.text, max(previous_start + 1, metadata["start"]))
        start = found if found >= 0 else metadata["start"]
        end = min(len(text), start + len(node.text))
        previous_start = start
        page, page_end = page_at(start), page_at(max(start, end - 1))
        for folded in metadata["folded"]:
            visit(folded, page_at(folded["start"]), page_at(folded["start"]))
        path = metadata["path"]
        section_ordinal = visit(metadata, page, page_end)
        if role(path) == "references":
            kind = "references"
        elif len(TABLE_ROW.findall(node.text)) >= 2:
            kind = "table"
        elif has_headings and role(path) == "front_matter":
            kind = "front_matter"
        else:
            kind = "text"
        heading = " > ".join(path)
        chunks.append(
            ChunkDraft(
                ordinal=len(chunks),
                section_ordinal=section_ordinal,
                section_path=list(path),
                heading=heading,
                kind=kind,
                page=page,
                page_end=page_end,
                bboxes=boxes_between(start, end),
                text=node.text,
                context_text="\n".join(filter(None, [title, heading, node.text])),
                token_count=counter.count(node.text),
            )
        )
    for path, entry in sections.items():  # A section's pages include its subsections.
        nested = [c.page_end for c in chunks if tuple(c.section_path[: len(path)]) == path]
        entry["page_end"] = max([entry["page_end"], *nested])
    drafts = [
        SectionDraft(
            ordinal=entry["ordinal"],
            title=path[-1],
            level=entry["level"],
            path=list(path),
            role=role(list(path)),
            page=entry["page"],
            page_end=entry["page_end"],
        )
        for path, entry in sections.items()
    ]
    return ChunkPlan(chunk_set=CHUNK_SET, sections=drafts, chunks=chunks)
