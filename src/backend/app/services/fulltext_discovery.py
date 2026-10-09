"""Exact-identity full-text discovery, independent of PDF downloading."""

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.integrations.academic import AcademicSearch, normalized_doi
from app.models.research import Paper, PaperSource
from app.repositories.papers import save_canonical
from app.schemas.fulltext import FullTextCandidate
from app.schemas.research import FullTextLocation, SearchResult


@dataclass
class DiscoveryResult:
    candidates: list[FullTextCandidate]
    warnings: list[str]


def candidates_from_sources(sources: list[SearchResult]) -> list[FullTextCandidate]:
    copies = []
    for source in sorted(sources, key=lambda item: (item.provider, item.external_id)):
        locations = list(source.locations)
        if source.pdf_url and not any(item.pdf_url == source.pdf_url for item in locations):
            locations.append(FullTextLocation(pdf_url=source.pdf_url, is_oa=source.is_open_access))
        for location in locations:
            if not location.pdf_url:
                continue
            try:
                url = urlunsplit(urlsplit(location.pdf_url)._replace(fragment=""))
            except ValueError:
                url = location.pdf_url
            copies.append(
                FullTextCandidate(
                    provider=source.provider,
                    external_id=source.external_id,
                    source_label="OpenAlex"
                    if source.provider == "openalex"
                    else "Semantic Scholar",
                    url=url,
                    location=location,
                )
            )
    versions = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}
    copies.sort(
        key=lambda item: (
            item.location.is_oa is not True,
            versions.get(item.location.version, 3),
            item.provider,
            item.url,
        )
    )
    unique = {}
    for item in copies:
        unique.setdefault(item.url, item)
    return list(unique.values())[:8]


async def discover_fulltext(resources, paper_id: UUID) -> DiscoveryResult:
    async with resources.sessions() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
        doi = normalized_doi(paper.doi)
        stored = list(
            (
                await session.scalars(select(PaperSource).where(PaperSource.paper_id == paper_id))
            ).all()
        )
        snapshots = {
            (item.provider, item.external_id): SearchResult.model_validate(item.metadata_snapshot)
            for item in stored
        }
    warnings = []
    adapter = AcademicSearch(resources.http, resources.settings)

    async def retain(result, *, identity=None):
        if result is None:
            return
        if (identity and (result.provider, result.external_id) != identity) or (
            doi and normalized_doi(result.doi) != doi
        ):
            warnings.append("Provider metadata no longer matches the saved paper identity.")
            return
        async with resources.sessions() as session, session.begin():
            updated, _ = await save_canonical(session, result)
            if updated.id != paper_id:
                raise AppError(
                    409,
                    "PAPER_IDENTITY_CONFLICT",
                    "The discovered copy belongs to another saved paper.",
                )
        snapshots[(result.provider, result.external_id)] = result

    try:
        async with asyncio.timeout(45):
            for provider in ("openalex", "semantic_scholar"):
                source = next(
                    (item for item in snapshots.values() if item.provider == provider), None
                )
                try:
                    if source:
                        await retain(
                            await adapter.canonical(provider, source.external_id),
                            identity=(provider, source.external_id),
                        )
                    elif doi:
                        await retain(await adapter.by_doi(provider, doi))
                except (AppError, ValueError, TypeError, KeyError):
                    warnings.append(
                        f"{provider} metadata could not be refreshed; stored links were retained."
                    )
    except TimeoutError:
        warnings.append("Provider discovery timed out; stored links were retained.")
    return DiscoveryResult(candidates_from_sources(list(snapshots.values())), warnings)
