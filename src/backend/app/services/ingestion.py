import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import UUID

from minio.error import S3Error
from sqlalchemy import delete, select, update

from app.integrations.academic import normalized_doi
from app.integrations.storage import read_object
from app.models.jobs import BackgroundJob
from app.models.research import Document, DocumentChunk, DocumentPage, Paper
from app.repositories.jobs import fence, now, retry_locked
from app.repositories.papers import identity_locks, replace_authors
from app.services.uploads import MAX_UPLOAD_BYTES


async def parse_in_child(data: bytes, deadline_seconds: float = 120) -> dict:
    with tempfile.TemporaryDirectory(prefix="ara-pdf-") as temporary:
        source, output = Path(temporary) / "original.pdf", Path(temporary) / "parsed.json"
        await asyncio.to_thread(source.write_bytes, data)
        # The parser gets no hosted keys or storage/database credentials.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "PYTHONPATH"}
        }
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.jobs.pdf_parser",
            str(source),
            str(output),
            env=environment,
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
        if process.returncode != 0 or not output.exists():
            return {
                "error": {
                    "code": "PDF_PARSE_FAILED",
                    "message": "The isolated PDF parser could not finish.",
                }
            }
        return json.loads(await asyncio.to_thread(output.read_text, encoding="utf-8"))


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
        if document and job.state == "failed":
            document.status = "failed"
            document.warnings = [message]


async def run_ingest_job(resources, job_id, generation, lease_token, payload):
    document_id = UUID(payload["document_id"])
    async with resources.sessions() as session:
        document = await session.get(Document, document_id)
        if document is None:
            await finish_failure(
                resources,
                job_id,
                generation,
                lease_token,
                document_id,
                "DOCUMENT_NOT_FOUND",
                "The uploaded document no longer exists.",
            )
            return
        object_key = document.object_key
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
    from app.integrations.llm import metadata_available

    if (not metadata.get("title") or not metadata.get("authors")) and await metadata_available(
        resources
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
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, lease_token)).with_for_update()
        )
        if job is None:
            return
        document = await session.get(Document, document_id)
        metadata_doi = normalized_doi(metadata.get("doi"))
        if metadata_doi:
            await identity_locks(session, [f"doi:{metadata_doi}"])
        paper = await session.scalar(
            select(Paper).where(Paper.id == document.paper_id).with_for_update()
        )
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
        await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        ordinal = 0
        for page in parsed["pages"]:
            session.add(DocumentPage(document_id=document_id, **page))
            text = page["text"]
            for start in range(0, len(text), 2720):
                passage = text[start : start + 3200]
                if not passage.strip():
                    continue
                session.add(
                    DocumentChunk(
                        document_id=document_id,
                        page=page["page"],
                        text=passage,
                        ordinal=ordinal,
                        # Interim page windows until ARA-071 replaces them with section chunks.
                        chunk_set="legacy-page-window-v0",
                        page_end=page["page"],
                        context_text=passage,
                        token_count=max(1, (len(passage.encode()) + 2) // 3),
                    )
                )
                ordinal += 1
        document.status, document.page_count = "ready", len(parsed["pages"])
        document.warnings, document.extractor_version = (
            parsed["warnings"],
            parsed["extractor_version"],
        )
        job.state, job.stage, job.progress = "completed", "completed", 100
        job.result = {"paper_id": str(paper.id), "document_id": str(document.id)}
        job.error_code, job.error_message = None, None
        job.lease_token, job.lease_expires_at = None, None
        job.updated_at = now()
