import asyncio
import json
import os
import sys
import tempfile
import weakref
from pathlib import Path
from uuid import UUID

from minio.error import S3Error
from sqlalchemy import delete, select, update

from app.integrations.academic import normalized_doi
from app.integrations.storage import read_object
from app.jobs.pdf_parser import THREAD_TUNING
from app.models.jobs import BackgroundJob
from app.models.research import Document, DocumentChunk, DocumentPage, Paper
from app.models.retrieval import DocumentSection
from app.rag import hooks
from app.rag.chunking import ChunkPlan, build_chunk_plan
from app.repositories.jobs import fence, now, retry_locked
from app.repositories.papers import identity_locks, replace_authors
from app.services.deletion import PAPER_DELETED, STOPPED, settle_deleted_locked
from app.services.metadata import queue_lookup
from app.services.upload_match import absorb, find_library_match, has_pdf, hold, note_doi_owner
from app.services.uploads import MAX_UPLOAD_BYTES

# One parse child per event loop: the 2 GiB worker cannot hold two layout models.
_parse_slots: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
# The layout pass gets this share of the deadline; the legacy fallback gets the rest.
LAYOUT_SHARE = 0.75


def parser_environment() -> dict[str, str]:
    # The parser gets no hosted keys or storage/database credentials.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "PYTHONPATH"}
    }
    # MALLOC_ARENA_MAX only takes effect when set before the child starts.
    environment.update(THREAD_TUNING)
    if os.environ.get("APP_ENV") == "test" and "ARA_PARSER_FORCE_LAYOUT_ERROR" in os.environ:
        environment["APP_ENV"] = "test"
        environment["ARA_PARSER_FORCE_LAYOUT_ERROR"] = os.environ["ARA_PARSER_FORCE_LAYOUT_ERROR"]
    return environment


def read_parsed(output: Path) -> dict | None:
    return json.loads(output.read_text(encoding="utf-8")) if output.exists() else None


async def run_parser(source: Path, output: Path, deadline_seconds: float, legacy: bool):
    """Return the child's JSON, a timeout error, or None when the child did not finish."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.jobs.pdf_parser",
        str(source),
        str(output),
        *(["--legacy"] if legacy else []),
        env=parser_environment(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), deadline_seconds)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        if asyncio.current_task().cancelling():
            raise
        return {
            "error": {
                "code": "PDF_PARSE_TIMEOUT",
                "message": "PDF extraction exceeded the 120-second limit.",
            }
        }
    if process.returncode != 0:
        return None
    return await asyncio.to_thread(read_parsed, output)


async def parse_in_child(data: bytes, deadline_seconds: float = 120, *, layout=True) -> dict:
    """Parse in a child process. `layout=False` skips the layout model, for callers that need
    only the PDF's metadata, which both passes extract alike (ARA-095)."""
    slot = _parse_slots.setdefault(asyncio.get_running_loop(), asyncio.Lock())
    async with slot:
        with tempfile.TemporaryDirectory(prefix="ara-pdf-") as temporary:
            directory = Path(temporary)
            source = directory / "original.pdf"
            await asyncio.to_thread(source.write_bytes, data)
            clock = asyncio.get_running_loop()
            started = clock.time()
            parsed = (
                await run_parser(
                    source, directory / "layout.json", deadline_seconds * LAYOUT_SHARE, False
                )
                if layout
                else None
            )
            if parsed is None or (parsed.get("error") or {}).get("code") == "PDF_PARSE_TIMEOUT":
                # A crashed or overlong layout pass gets one fresh child without the layout
                # model, within what remains of the deadline. Both parses share one chunk set.
                remaining = deadline_seconds - (clock.time() - started)
                parsed = await run_parser(source, directory / "legacy.json", remaining, True)
            if parsed is None:
                return {
                    "error": {
                        "code": "PDF_PARSE_FAILED",
                        "message": "The isolated PDF parser could not finish.",
                    }
                }
            return parsed


async def add_chunk_plan(session, document_id: UUID, plan: ChunkPlan) -> None:
    sections = {
        section.ordinal: DocumentSection(
            document_id=document_id,
            chunk_set=plan.chunk_set,
            ordinal=section.ordinal,
            title=section.title,
            level=section.level,
            path=section.path,
            role=section.role,
            page=section.page,
            page_end=section.page_end,
        )
        for section in plan.sections
    }
    session.add_all(sections.values())
    await session.flush()
    session.add_all(
        DocumentChunk(
            document_id=document_id,
            chunk_set=plan.chunk_set,
            ordinal=chunk.ordinal,
            section_id=sections[chunk.section_ordinal].id
            if chunk.section_ordinal is not None
            else None,
            section_path=chunk.section_path,
            heading=chunk.heading,
            kind=chunk.kind,
            page=chunk.page,
            page_end=chunk.page_end,
            text=chunk.text,
            context_text=chunk.context_text,
            bboxes=chunk.bboxes,
            token_count=chunk.token_count,
        )
        for chunk in plan.chunks
    )


async def finish_failure(
    resources, job_id, generation, token, document_id, code, message, *, permanent=True
):
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return
        document = await session.get(Document, document_id)
        if permanent:
            job.state, job.stage = "failed", "failed"
            job.error_code, job.error_message = code, message
            job.lease_token, job.lease_expires_at = None, None
            job.updated_at = now()
        else:
            retry_locked(session, job, code=code, message=message)
        # A failed re-ingest leaves a ready document ready, with whatever chunks it had.
        if document and job.state == "failed" and document.status != "ready":
            document.status = "failed"
            document.warnings = [message]


async def complete_pending(session, job, document_id, placeholder_id, match) -> None:
    """Finish the ingest job before storing pages: the user chooses Replace or Cancel, and
    nothing paid starts meanwhile. The document stays processing until it is resolved."""
    job.state, job.stage, job.progress = "completed", "completed", 100
    job.result = {
        "paper_id": str(placeholder_id),
        "document_id": str(document_id),
        "outcome": "match_pending",
        "match": await hold(
            session,
            placeholder_id=placeholder_id,
            document_id=document_id,
            match=match,
            found_by="ingest",
        ),
    }
    job.error_code, job.error_message = None, None
    job.lease_token, job.lease_expires_at = None, None
    job.updated_at = now()


async def hold_for_decision(
    resources, job_id, generation, lease_token, document_id, placeholder_id, match
):
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, lease_token)).with_for_update()
        )
        if job is not None:
            await complete_pending(session, job, document_id, placeholder_id, match)


async def run_ingest_job(resources, job_id, generation, lease_token, payload):
    document_id = UUID(payload["document_id"])
    async with resources.sessions() as session:
        document = await session.get(Document, document_id)
        if document is None:
            # Documents go only with their paper (ARA-095).
            await finish_failure(
                resources, job_id, generation, lease_token, document_id, PAPER_DELETED, STOPPED
            )
            return
        object_key, placeholder_id = document.object_key, document.paper_id
    try:
        data = await resources.storage_call(
            read_object,
            resources.storage,
            resources.settings.minio_bucket,
            object_key,
            MAX_UPLOAD_BYTES,
        )
    except S3Error as error:
        await finish_failure(
            resources,
            job_id,
            generation,
            lease_token,
            document_id,
            "STORAGE_OBJECT_MISSING" if error.code == "NoSuchKey" else "STORAGE_UNAVAILABLE",
            "The retained PDF could not be read from storage.",
            permanent=error.code == "NoSuchKey",
        )
        return
    except Exception:
        await finish_failure(
            resources,
            job_id,
            generation,
            lease_token,
            document_id,
            "STORAGE_UNAVAILABLE",
            "PDF storage is unavailable; extraction will retry.",
            permanent=False,
        )
        return
    parsed = await parse_in_child(data)
    if parsed.get("error"):
        await finish_failure(
            resources,
            job_id,
            generation,
            lease_token,
            document_id,
            parsed["error"]["code"],
            parsed["error"]["message"],
        )
        return
    metadata = parsed["metadata"]
    enriched_fields = set()
    first_pages = "\n".join(page["text"] for page in parsed["pages"][:2])
    # A new upload that is a library paper joins it (ARA-086); that paper already has its
    # bibliography, so no model is asked for one.
    match = None
    if payload.get("new_paper"):
        async with resources.sessions() as session:
            match = await find_library_match(session, placeholder_id, metadata, first_pages)
    from app.integrations.llm import metadata_available

    if (
        match is None
        and (not metadata.get("title") or not metadata.get("authors"))
        and await metadata_available(resources)
    ):
        enrichment = payload.get("metadata_result") or {}
        if not payload.get("metadata_attempted"):
            payload["metadata_attempted"] = True
            async with resources.sessions() as session, session.begin():
                checkpoint = await session.scalar(
                    update(BackgroundJob)
                    .where(*fence(job_id, generation, lease_token))
                    .values(payload=dict(payload), stage="extracting_metadata", progress=50)
                    .returning(BackgroundJob.id)
                )
                if checkpoint is None:
                    return
            try:
                from app.integrations.llm import extract_metadata

                enrichment = await extract_metadata(
                    resources, "\n".join(page["text"] for page in parsed["pages"][:2])
                )
                payload["metadata_result"] = enrichment
            except Exception:
                parsed["warnings"].append(
                    "Model metadata enrichment was unavailable; extracted text was retained."
                )
            async with resources.sessions() as session, session.begin():
                saved = await session.scalar(
                    update(BackgroundJob)
                    .where(*fence(job_id, generation, lease_token))
                    .values(payload=dict(payload))
                    .returning(BackgroundJob.id)
                )
                if saved is None:
                    return
        elif not enrichment:
            parsed["warnings"].append(
                "Prior metadata inference was interrupted; extracted text was retained."
            )
        for key, value in enrichment.items():
            if value and not metadata.get(key):
                metadata[key] = value
                enriched_fields.add(key)
        if payload.get("new_paper") and enriched_fields & {"doi", "title"}:
            async with resources.sessions() as session:
                match = await find_library_match(session, placeholder_id, metadata, first_pages)
    if match is not None and match.has_pdf:
        await hold_for_decision(
            resources, job_id, generation, lease_token, document_id, placeholder_id, match
        )
        return
    async with resources.sessions() as session:
        known_title = await session.scalar(
            select(Paper.title)
            .join(Document, Document.paper_id == Paper.id)
            .where(Document.id == document_id)
        )
    # LlamaIndex chunking is CPU-bound; keep it off the event loop and outside row locks.
    plan = await asyncio.to_thread(
        build_chunk_plan, parsed["pages"], title=known_title or metadata.get("title")
    )
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, lease_token)).with_for_update()
        )
        if job is None:
            return
        metadata_doi = normalized_doi(metadata.get("doi"))
        if metadata_doi:
            await identity_locks(session, [f"doi:{metadata_doi}"])
        # Deleting a paper locks it before its PDFs go (ARA-095). Once the paper is locked here,
        # a document that is still there stays until this commit.
        owner = await session.scalar(select(Document.paper_id).where(Document.id == document_id))
        locked = {
            paper.id: paper
            for paper in (
                await session.scalars(
                    select(Paper)
                    .where(Paper.id.in_({owner, *([match.paper_id] if match else [])}))
                    .order_by(Paper.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        }
        document = await session.get(Document, document_id) if owner in locked else None
        if document is None:
            settle_deleted_locked(job)
            return
        attached = None
        if match is not None:
            library = locked.get(match.paper_id)
            if library is not None and await has_pdf(session, library):
                # It received a PDF meanwhile: ask instead of attaching.
                await complete_pending(session, job, document_id, placeholder_id, match)
                return
            if library is not None:
                await absorb(
                    session, placeholder_id=placeholder_id, library=library, document=document
                )
                attached = {
                    "paper_id": str(library.id),
                    "outcome": "attached",
                    "matched_by": match.matched_by,
                }
        paper = await session.scalar(
            select(Paper).where(Paper.id == document.paper_id).with_for_update()
        )
        if not payload.get("new_paper"):
            await note_doi_owner(session, document.id, paper, metadata_doi)
        provenance = dict(paper.metadata_provenance)
        for key in ("title", "year", "abstract", "doi"):
            value = metadata.get(key)
            if (
                value is None
                or getattr(paper, key) is not None
                or (provenance.get(key) or {}).get("source") == "manual"
            ):
                continue
            if key == "doi":
                value = normalized_doi(value)
                conflict = (
                    await session.scalar(
                        select(Paper.id).where(Paper.normalized_doi == value, Paper.id != paper.id)
                    )
                    if value
                    else None
                )
                if conflict:
                    parsed["warnings"].append(
                        "PDF DOI matches another paper; reconcile bibliographic records manually."
                    )
                    continue
                paper.normalized_doi = value
            setattr(paper, key, value)
            provenance[key] = (
                {"source": "llm", "model": resources.settings.default_model}
                if key in enriched_fields
                else {"source": "pdf"}
            )
        if metadata.get("authors") and not provenance.get("authors"):
            await replace_authors(session, paper.id, metadata["authors"])
            provenance["authors"] = (
                {"source": "llm", "model": resources.settings.default_model}
                if "authors" in enriched_fields
                else {"source": "pdf"}
            )
        paper.metadata_provenance = provenance
        await queue_lookup(
            session, paper, document.id, metadata, new_paper=bool(payload.get("new_paper"))
        )
        await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        await session.execute(
            delete(DocumentSection).where(DocumentSection.document_id == document_id)
        )
        session.add_all(
            DocumentPage(
                document_id=document_id,
                page=page["page"],
                text=page["text"],
                printed_label=page["printed_label"],
            )
            for page in parsed["pages"]
        )
        await add_chunk_plan(session, document_id, plan)
        became_ready = document.status != "ready"
        document.status, document.page_count = "ready", len(parsed["pages"])
        document.warnings, document.extractor_version = (
            parsed["warnings"],
            parsed["extractor_version"],
        )
        document.parser, document.chunk_set = parsed["parser"], plan.chunk_set
        job.state, job.stage, job.progress = "completed", "completed", 100
        job.result = {"paper_id": str(paper.id), "document_id": str(document.id)}
        if attached:
            job.result["match"] = attached
        job.error_code, job.error_message = None, None
        job.lease_token, job.lease_expires_at = None, None
        job.updated_at = now()
        await session.flush()
        await hooks.after_chunks_persisted(session, document_id=document.id)
        if became_ready:
            from app.services.summarization import queue_automatic_summary

            await queue_automatic_summary(session, resources, document)
