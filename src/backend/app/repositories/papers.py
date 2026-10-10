from uuid import UUID

from sqlalchemy import delete, func, select, tuple_

from app.core.errors import AppError
from app.integrations.academic import normalized_doi
from app.models.research import Document, Paper, PaperAuthor, PaperSource
from app.schemas.research import PaperDetail, PaperPatch, SearchHit, SearchResult


async def identity_locks(session, keys: list[str]) -> None:
    for key in sorted(set(keys)):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def replace_authors(session, paper_id: UUID, names: list[str]) -> None:
    await session.execute(delete(PaperAuthor).where(PaperAuthor.paper_id == paper_id))
    session.add_all(
        [
            PaperAuthor(paper_id=paper_id, ordinal=index, name=name[:300])
            for index, name in enumerate(names[:50])
        ]
    )


async def save_canonical(session, result: SearchResult) -> tuple[Paper, bool]:
    doi = normalized_doi(result.doi)
    keys = [f"source:{result.provider}:{result.external_id}"] + ([f"doi:{doi}"] if doi else [])
    await identity_locks(session, keys)
    source = await session.scalar(
        select(PaperSource).where(
            PaperSource.provider == result.provider, PaperSource.external_id == result.external_id
        )
    )
    paper = await session.get(Paper, source.paper_id) if source else None
    matched = (
        await session.scalar(select(Paper).where(Paper.normalized_doi == doi)) if doi else None
    )
    if paper and matched and paper.id != matched.id:
        raise AppError(
            409,
            "PAPER_IDENTITY_CONFLICT",
            "The provider identity and DOI belong to different papers.",
        )
    paper = paper or matched
    created = paper is None
    if paper is not None:
        paper = await session.scalar(
            select(Paper)
            .where(Paper.id == paper.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if paper is None:
            raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    if paper is None:
        paper = Paper(
            title=result.title,
            year=result.year,
            abstract=result.abstract,
            doi=doi,
            normalized_doi=doi,
            metadata_provenance={},
        )
        session.add(paper)
        await session.flush()
        await replace_authors(session, paper.id, result.authors)
    provenance = dict(paper.metadata_provenance)
    for field in ("title", "year", "abstract", "doi"):
        value = getattr(result, field)
        if (
            value is not None
            and (created or getattr(paper, field) is None)
            and (provenance.get(field) or {}).get("source") != "manual"
        ):
            setattr(paper, field, doi if field == "doi" else value)
            if field == "doi":
                paper.normalized_doi = doi
            provenance[field] = {"source": result.provider}
    if created and result.authors:
        provenance["authors"] = {"source": result.provider}
    paper.metadata_provenance = provenance
    if source is None:
        source = PaperSource(
            paper_id=paper.id,
            provider=result.provider,
            external_id=result.external_id,
            metadata_snapshot=result.model_dump(mode="json"),
        )
        session.add(source)
    else:
        source.metadata_snapshot = result.model_dump(mode="json")
    await session.flush()
    return paper, created


async def mark_saved(session, hits: list[SearchHit]) -> None:
    """Match hits to the library like save_canonical: provider record first, then DOI."""
    if not hits:
        return
    identities = {(hit.provider, hit.external_id) for hit in hits}
    by_source = {
        (provider, external_id): paper_id
        for provider, external_id, paper_id in await session.execute(
            select(PaperSource.provider, PaperSource.external_id, PaperSource.paper_id).where(
                tuple_(PaperSource.provider, PaperSource.external_id).in_(identities)
            )
        )
    }
    dois = {doi for hit in hits if (doi := normalized_doi(hit.doi))}
    by_doi = (
        dict(
            (
                await session.execute(
                    select(Paper.normalized_doi, Paper.id).where(Paper.normalized_doi.in_(dois))
                )
            ).all()
        )
        if dois
        else {}
    )
    for hit in hits:
        hit.saved_paper_id = by_source.get((hit.provider, hit.external_id)) or by_doi.get(
            normalized_doi(hit.doi)
        )


async def paper_detail(session, paper_id: UUID, *, follow: bool = True) -> PaperDetail:
    from app.services.upload_match import match_view, redirect_target

    paper = await session.get(Paper, paper_id)
    if paper is None:
        # An upload that joined a library paper answers as that paper (ARA-086).
        target = await redirect_target(session, paper_id) if follow else None
        if target is not None:
            return await paper_detail(session, target, follow=False)
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    authors = (
        await session.scalars(
            select(PaperAuthor.name)
            .where(PaperAuthor.paper_id == paper.id)
            .order_by(PaperAuthor.ordinal)
        )
    ).all()
    sources = (
        await session.scalars(select(PaperSource).where(PaperSource.paper_id == paper.id))
    ).all()
    document = (
        await session.get(Document, paper.active_document_id) if paper.active_document_id else None
    )
    upload_match, pdf_doi_owner = await match_view(session, paper)
    status = document.status if document else "metadata_only"
    if status == "uploading":
        status = "processing"
    snapshots = [SearchResult.model_validate(x.metadata_snapshot) for x in sources]
    # The venue lives in the provider record its provenance names, else any record (ARA-086);
    # a venue the user edited lives in its provenance entry (ARA-095).
    venue_origin = paper.metadata_provenance.get("venue") or {}
    venue_source = venue_origin.get("source")
    venue = (
        venue_origin.get("value")
        if venue_source == "manual"
        else next(
            (
                x.venue
                for x in sorted(snapshots, key=lambda x: x.provider != venue_source)
                if x.venue
            ),
            None,
        )
    )
    return PaperDetail(
        id=paper.id,
        title=paper.title,
        authors=list(authors),
        year=paper.year,
        abstract=paper.abstract,
        doi=paper.doi,
        venue=venue,
        sources=snapshots,
        document_status=status,
        active_document_id=paper.active_document_id,
        metadata_provenance=paper.metadata_provenance,
        file_name=document.original_filename if document else None,
        upload_match=upload_match,
        pdf_doi_owner=pdf_doi_owner,
    )


async def patch_paper(session, paper_id: UUID, patch: PaperPatch) -> PaperDetail:
    updates = patch.model_dump(exclude_unset=True)
    if "doi" in updates and updates["doi"] is not None:
        doi = normalized_doi(updates["doi"])
        if doi is None:
            raise AppError(422, "INVALID_DOI", "Enter a valid DOI such as 10.1000/example.")
        updates["doi"] = doi
        await identity_locks(session, [f"doi:{doi}"])
        duplicate = await session.scalar(
            select(Paper.id).where(Paper.normalized_doi == doi, Paper.id != paper_id)
        )
        if duplicate:
            raise AppError(
                409, "DOI_ALREADY_SAVED", "This DOI already belongs to another saved paper."
            )
    paper = await session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    provenance = dict(paper.metadata_provenance)
    for field, value in updates.items():
        provenance[field] = {"source": "manual"}
        if field == "authors":
            await replace_authors(session, paper.id, value or [])
        elif field == "venue":
            provenance[field]["value"] = (value.strip() or None) if value else None
        else:
            setattr(paper, field, value)
            if field == "doi":
                paper.normalized_doi = value
    paper.metadata_provenance = provenance
    paper.updated_at = func.now()
    await session.flush()
    return await paper_detail(session, paper_id)
