"""Adapter: run legacy citation cases (ARA-052) against the passage-based validator (ARA-073)."""

from app.rag.citations import passage_citations
from app.rag.packing import Passage


def validate_citations(content, chunks, document_id):
    passages = [
        Passage(
            handle=f"S{index}",
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            page=chunk.page,
            page_end=chunk.page,
            section="",
            kind="text",
            text=chunk.text,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    return passage_citations(content, passages, {document_id})
