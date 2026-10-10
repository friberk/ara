"""A ready paper with real sections and chunks, for section-summary tests (ARA-079)."""

from uuid import uuid4

from app.integrations.embedding_catalog import PROFILES
from app.models.research import Document, DocumentChunk, Paper, PaperAuthor
from app.models.retrieval import ChunkEmbedding, DocumentSection, RetrievalIndex
from tests.support.vectors import fixture_vector

CHUNK_SET = "layout-v1:sections"
TITLE = "Sparse Retrieval for Scientific QA"
# (path, role, page, [chunk texts]); a section's chunks sit directly under it.
OUTLINE = [
    (["Abstract"], "front_matter", 1, ["We study sparse retrieval for scientific questions."]),
    (["1 Introduction"], "body", 1, ["Researchers ask precise questions about baselines."]),
    (
        ["2 Method"],
        "body",
        2,
        [
            "We index every passage with BM25 using the Okapi weighting.",
            "Passages are split at section boundaries and capped at 512 tokens.",
        ],
    ),
    (
        ["2 Method", "2.1 Dense baseline"],
        "body",
        3,
        [
            "The dense baseline encodes passages with a bi-encoder.",
            "Its index stores one vector per passage.",
        ],
    ),
    (
        ["3 Limitations"],
        "body",
        4,
        [
            "BM25 misses paraphrases that share no words with the question.",
            "The benchmark has only 120 questions, so differences are not significant.",
        ],
    ),
    (["References"], "references", 5, ["[1] Robertson. BM25.", "[2] Karpukhin. DPR."]),
]


async def seed_sections(
    resources,
    *,
    outline=OUTLINE,
    title: str = TITLE,
    profile: str | None = None,
    chunk_set: str = CHUNK_SET,
    active: bool = True,
):
    """Returns (paper_id, document_id, {section path tuple: [chunk ids in order]})."""
    async with resources.sessions() as session, session.begin():
        paper = Paper(id=uuid4(), title=title, year=2024)
        session.add(paper)
        await session.flush()
        session.add(PaperAuthor(paper_id=paper.id, ordinal=0, name="Ada Researcher"))
        document = Document(
            id=uuid4(),
            paper_id=paper.id,
            status="ready",
            object_key=f"documents/{uuid4()}.pdf",
            sha256=uuid4().hex + uuid4().hex,
            original_filename="sections.pdf",
            byte_size=10,
            request_id=uuid4(),
            page_count=5,
            chunk_set=chunk_set,
            parser="pymupdf4llm-layout",
        )
        session.add(document)
        await session.flush()
        if active:
            paper.active_document_id = document.id
        chunks, found, ordinal = [], {}, 0
        for number, (path, role, page, texts) in enumerate(outline):
            section = DocumentSection(
                document_id=document.id,
                chunk_set=chunk_set,
                ordinal=number,
                title=path[-1],
                level=len(path),
                path=path,
                role=role,
                page=page,
                page_end=page,
            )
            session.add(section)
            await session.flush()
            kind = {"front_matter": "front_matter", "references": "references"}.get(role, "text")
            for text in texts:
                chunk = DocumentChunk(
                    id=uuid4(),
                    document_id=document.id,
                    chunk_set=chunk_set,
                    ordinal=ordinal,
                    section_id=section.id,
                    section_path=path,
                    heading=" > ".join(path),
                    kind=kind,
                    page=page,
                    page_end=page,
                    text=text,
                    context_text=f"{title}\n{' > '.join(path)}\n{text}",
                    bboxes=[[page, 72.0, 90.0, 540.0, 180.0]],
                    token_count=len(text.split()),
                )
                chunks.append(chunk)
                found.setdefault(tuple(path), []).append(chunk.id)
                ordinal += 1
        session.add_all(chunks)
        await session.flush()
        if profile is not None:
            dims = PROFILES[profile].dimensions
            session.add_all(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    profile=profile,
                    document_id=document.id,
                    embedding=fixture_vector(chunk.context_text, dims),
                    input_hash="fixture",
                )
                for chunk in chunks
            )
            session.add(
                RetrievalIndex(
                    document_id=document.id,
                    profile=profile,
                    chunk_set=chunk_set,
                    state="ready",
                    embedded=len(chunks),
                    total=len(chunks),
                )
            )
        return paper.id, document.id, found
