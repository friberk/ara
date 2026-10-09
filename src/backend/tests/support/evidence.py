"""A ready, structured paper with fixture embeddings, for retrieval and answer tests (ARA-073).

The sections mirror tests/support/structured_pdf.py, so expectations read like the real paper.
"""

from uuid import uuid4

from app.integrations.embedding_catalog import PROFILES
from app.models.research import Document, DocumentChunk, Paper, PaperAuthor
from app.models.retrieval import ChunkEmbedding, RetrievalIndex
from tests.support.vectors import fixture_vector

TITLE = "Sparse Retrieval for Scientific QA"
CHUNK_SET = "layout-v1:evidence"
OPENAI = "openai-3-large"
# (heading, kind, page, page_end, text)
SECTIONS = [
    (
        "Abstract",
        "front_matter",
        1,
        1,
        "We study sparse retrieval for question answering over scientific papers. A lexical "
        "BM25 index is compared with dense vectors on a synthetic benchmark of 120 questions.",
    ),
    (
        "1 Introduction",
        "text",
        2,
        2,
        "Researchers ask precise questions about datasets, baselines and limitations. Retrieval "
        "must find the passage that answers each question before a model writes an answer.",
    ),
    (
        "2 Method",
        "text",
        2,
        3,
        "We index every passage with BM25 using the Okapi weighting and a stemmed English "
        "vocabulary. Passages are split at section boundaries and capped at 512 tokens. The "
        "dense baseline encodes the same passages with a bi-encoder trained on scientific text.",
    ),
    (
        "3 Results",
        "table",
        3,
        3,
        "Table 1 reports recall at ten retrieved passages and median latency.\n\n"
        "| Model | Recall@10 | Latency (ms) |\n|---|---|---|\n| BM25 | 0.61 | 4 |\n"
        "| Dense | 0.72 | 19 |\n\nDense retrieval improves recall while BM25 remains five "
        "times faster.",
    ),
    (
        "References",
        "references",
        4,
        4,
        "[1] S. Robertson and H. Zaragoza. The probabilistic relevance framework: BM25 and "
        "beyond. [2] V. Karpukhin et al. Dense passage retrieval for open-domain question "
        "answering.",
    ),
]


def embedding_rows(document_id, chunks, profile: str):
    dims = PROFILES[profile.removesuffix("#r")].dimensions
    return [
        ChunkEmbedding(
            chunk_id=chunk.id,
            profile=profile,
            document_id=document_id,
            embedding=fixture_vector(chunk.context_text, dims),
            input_hash="fixture",
        )
        for chunk in chunks
    ]


async def seed_structured(
    resources,
    *,
    sections=SECTIONS,
    title: str = TITLE,
    profile: str | None = OPENAI,
    index_state: str | None = "ready",
    chunk_set: str = CHUNK_SET,
) -> tuple:
    """Returns (paper_id, document_id, chunk ids in ordinal order)."""
    async with resources.sessions() as session, session.begin():
        paper = Paper(id=uuid4(), title=title, year=2024)
        session.add(paper)
        await session.flush()
        session.add_all(
            [
                PaperAuthor(paper_id=paper.id, ordinal=0, name="Ada Researcher"),
                PaperAuthor(paper_id=paper.id, ordinal=1, name="Ben Analyst"),
            ]
        )
        document = Document(
            id=uuid4(),
            paper_id=paper.id,
            status="ready",
            object_key=f"documents/{uuid4()}.pdf",
            sha256=uuid4().hex + uuid4().hex,
            original_filename="structured.pdf",
            byte_size=10,
            request_id=uuid4(),
            page_count=4,
            chunk_set=chunk_set,
            parser="pymupdf4llm-layout",
        )
        session.add(document)
        await session.flush()
        paper.active_document_id = document.id
        chunks = [
            DocumentChunk(
                id=uuid4(),
                document_id=document.id,
                chunk_set=chunk_set,
                ordinal=ordinal,
                section_path=[heading],
                heading=heading,
                kind=kind,
                page=page,
                page_end=page_end,
                text=text,
                context_text=f"{title}\n{heading}\n{text}",
                token_count=len(text.split()),
            )
            for ordinal, (heading, kind, page, page_end, text) in enumerate(sections)
        ]
        session.add_all(chunks)
        await session.flush()
        if profile is not None:
            session.add_all(embedding_rows(document.id, chunks, profile))
            if index_state is not None:
                session.add(
                    RetrievalIndex(
                        document_id=document.id,
                        profile=profile,
                        chunk_set=chunk_set,
                        state=index_state,
                        embedded=len(chunks),
                        total=len(chunks),
                    )
                )
        return paper.id, document.id, [chunk.id for chunk in chunks]
