import json
import subprocess
import sys

import httpx
import pytest


def test_provider_overrides_are_rejected_outside_test():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="test"):
        Settings(
            app_env="development", openalex_base_url="http://fixtures:8090/openalex", _env_file=None
        )
    assert Settings(
        app_env="test", openalex_base_url="http://fixtures:8090/openalex", _env_file=None
    )


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
async def test_search_normalizes_nullable_fields_and_paginates(provider):
    """Given scholarly fixtures, when searched, then nullable metadata and cursors remain honest."""
    from app.core.config import Settings
    from app.integrations.academic import AcademicSearch

    def respond(request):
        if provider == "openalex":
            assert request.url.params["search"] == "retrieval"
            return httpx.Response(
                200,
                json={
                    "meta": {"count": 3, "next_cursor": "next=="},
                    "results": [
                        {
                            "id": "https://openalex.org/W123",
                            "display_name": "Grounded research",
                            "publication_year": 2024,
                            "doi": "https://doi.org/10.1000/fixture",
                            "authorships": [{"author": {"display_name": "A. Researcher"}}],
                            "abstract_inverted_index": {"Grounded": [0], "research": [1]},
                            "primary_location": {
                                "landing_page_url": "https://example.org/paper",
                                "pdf_url": None,
                            },
                        },
                        {"id": "https://openalex.org/W124", "display_name": None},
                    ],
                },
            )
        assert request.url.params["query"] == "retrieval"
        return httpx.Response(
            200,
            json={
                "total": 3,
                "next": 2,
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Grounded research",
                        "year": 2024,
                        "externalIds": {"DOI": "10.1000/fixture"},
                        "authors": [{"name": "A. Researcher"}],
                        "abstract": "Grounded research",
                        "url": "https://example.org/paper",
                        "openAccessPdf": None,
                    },
                    {"paperId": "abc124", "title": None},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        page = await AcademicSearch(client, Settings(_env_file=None)).search(
            provider, "retrieval", None, 2
        )
    assert page.provider == provider and page.total == 3 and page.next_cursor is not None
    assert page.items[0].doi == "10.1000/fixture"
    assert page.items[0].abstract == "Grounded research"
    assert page.items[0].authors == ["A. Researcher"] and page.items[0].pdf_url is None
    assert page.items[1].title is None and page.items[1].year is None


async def test_search_rate_limit_is_actionable_and_invalid_cursor_never_reaches_provider():
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.integrations.academic import AcademicSearch

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "30"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = AcademicSearch(client, Settings(_env_file=None))
        with pytest.raises(AppError) as failure:
            await adapter.search("semantic_scholar", "query", None, 20)
        assert failure.value.status_code == 429 and failure.value.code == "PROVIDER_RATE_LIMITED"
        with pytest.raises(AppError) as failure:
            await adapter.search("semantic_scholar", "query", "http://evil.example", 20)
        assert failure.value.status_code == 422
    assert len(requests) == 1


async def test_unsafe_unknown_origin_rejected_before_parsing_request():
    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/documents",
            content=b"invalidmultipart",
            headers={
                "Origin": "https://untrusted.example",
                "Content-Type": "multipart/form-data",
            },
        )
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_NOT_ALLOWED"


def test_isolated_pdf_parser_preserves_pages_and_nullable_publication_metadata(tmp_path):
    """Given a synthetic PDF, when parsed in a child process, then physical pages remain intact."""
    import pymupdf

    document = pymupdf.open()
    for text in [
        "Synthetic Research\nAbstract\nGrounded retrieval improves accuracy.\n"
        "Introduction\nFirst-page evidence.",
        "Experiments\nThe blue condition achieved 87 percent accuracy.\nDOI: 10.1000/synthetic",
    ]:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.set_metadata(
        {
            "title": "Synthetic Research",
            "author": "Ada Researcher; Grace Scholar",
            "creationDate": "D:20261201000000",
        }
    )
    source = tmp_path / "fixture.pdf"
    document.save(source)
    document.close()
    output = tmp_path / "parsed.json"
    result = subprocess.run(
        [sys.executable, "-m", "app.jobs.pdf_parser", str(source), str(output)],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
    parsed = json.loads(output.read_text())
    assert [page["page"] for page in parsed["pages"]] == [1, 2]
    assert "87 percent" in parsed["pages"][1]["text"]
    assert parsed["metadata"]["title"] == "Synthetic Research"
    assert parsed["metadata"]["authors"] == ["Ada Researcher", "Grace Scholar"]
    assert parsed["metadata"]["year"] is None
    assert parsed["metadata"]["doi"] == "10.1000/synthetic"


def test_parser_reports_scanned_encrypted_and_malformed_failures(tmp_path):
    import pymupdf

    for name, encrypted in [("scanned", False), ("encrypted", True)]:
        doc = pymupdf.open()
        doc.new_page()
        path = tmp_path / f"{name}.pdf"
        options = (
            {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "secret"}
            if encrypted
            else {}
        )
        doc.save(path, **options)
        doc.close()
        output = tmp_path / f"{name}.json"
        subprocess.run(
            [sys.executable, "-m", "app.jobs.pdf_parser", str(path), str(output)],
            check=True,
            timeout=10,
        )
        assert json.loads(output.read_text())["error"]["code"] == (
            "PDF_PASSWORD_REQUIRED" if encrypted else "OCR_REQUIRED"
        )
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"%PDF-1.7\nthis is not a real document")
    output = tmp_path / "broken.json"
    subprocess.run(
        [sys.executable, "-m", "app.jobs.pdf_parser", str(source), str(output)],
        check=True,
        timeout=10,
    )
    assert json.loads(output.read_text())["error"]["code"] == "INVALID_PDF"


async def test_parser_timeout_kills_and_waits_for_child():
    from app.services.ingestion import parse_in_child

    result = await parse_in_child(b"%PDF-1.7\nminimal", deadline_seconds=0.00001)
    assert result["error"]["code"] == "PDF_PARSE_TIMEOUT"


def test_parser_rejects_more_than_200_pages(tmp_path):
    import pymupdf

    document = pymupdf.open()
    for _ in range(201):
        document.new_page()
    source = tmp_path / "too-many.pdf"
    output = tmp_path / "error.json"
    document.save(source)
    document.close()
    subprocess.run(
        [sys.executable, "-m", "app.jobs.pdf_parser", str(source), str(output)],
        check=True,
        timeout=10,
    )
    assert json.loads(output.read_text())["error"]["code"] == "PDF_PAGE_LIMIT"
