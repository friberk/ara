"""After an upload, the PDF supplies title, authors, year and abstract (ARA-117).

These run the pipeline as it ships: the real parser and ingest job, the real model fallback with
only the model's HTTP call mocked, then the real lookup against providers that find nothing. A
required field that is still empty after all of that is an application bug (ARA-118). Parser-only
behaviour is covered separately in test_pdf_metadata.py and is not evidence of a bug by itself.
"""

import json

import httpx
import pymupdf
import pytest
from pydantic import SecretStr
from support.academic import providers
from test_metadata_enrichment_integration import detail, ingested, run_lookup

from tests.test_ai import response_payload

pytestmark = pytest.mark.integration

TITLE = "Grounded Retrieval for Research Assistants"
AUTHORS = ["Ada Researcher", "Grace Scholar"]
BYLINE = "Ada Researcher and Grace Scholar"
ABSTRACT_LINES = (
    "We study grounded retrieval for research",
    "assistants and report measured accuracy",
    "on a held-out benchmark of questions.",
)
ABSTRACT = " ".join(ABSTRACT_LINES)
INFO = {"title": TITLE, "author": "Ada Researcher; Grace Scholar"}
VENUE_2023 = "Proceedings of the 2023 ACM Conference on Research."


def single_column(front_matter: str, **info) -> bytes:
    document = pymupdf.open()
    if info:
        document.set_metadata(info)
    page = document.new_page()
    page.insert_text((72, 80), TITLE, fontsize=20)
    page.insert_textbox(pymupdf.Rect(72, 110, 540, 720), front_matter, fontsize=10)
    data = document.tobytes()
    document.close()
    return data


def two_column() -> bytes:
    """Conference layout: each right-column line shares a baseline with a left-column line."""
    left = ("Abstract", *ABSTRACT_LINES, "1 Introduction")
    right = (
        "Prior work measured recall alone, which",
        "says little about whether an answer is",
        "supported by the passages it cites, so",
        "we measure citation support directly",
        "and report it for every question.",
    )
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((54, 80), TITLE, fontsize=20)
    page.insert_text((54, 110), BYLINE, fontsize=11)
    page.insert_text((54, 128), "35th Conference on Research, August 12-14, 2026", fontsize=11)
    for line, (first, second) in enumerate(zip(left, right, strict=True)):
        page.insert_text((54, 170 + line * 14), first, fontsize=10)
        page.insert_text((320, 170 + line * 14), second, fontsize=10)
    data = document.tobytes()
    document.close()
    return data


def printed_only() -> bytes:
    """No embedded details and an abstract style the parser does not read."""
    return single_column(f"{BYLINE}\n{VENUE_2023}\nAbstract—{ABSTRACT}\nI. INTRODUCTION\nBody.")


def embedded_title_and_authors() -> bytes:
    """Title and authors are embedded; year and abstract are only printed."""
    return single_column(f"{VENUE_2023}\nAbstract—{ABSTRACT}\nI. INTRODUCTION\nBody.", **INFO)


@pytest.fixture
def model(resources, monkeypatch):
    """The default model, mocked at HTTP: it answers with what the paper prints."""
    from app.integrations import llm
    from app.integrations.llm import HostedLLM

    # Load every module that does `from ...llm import create_llm` first. One imported while the
    # patch below is active would keep this mock for the rest of the test run.
    from app.main import create_app  # noqa: F401

    answer, calls = {}, []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload(json.dumps(answer)))

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    monkeypatch.setattr(
        llm,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ),
    )
    return answer, calls


async def no_provider_match(resources) -> list:
    requests = []
    await resources.http.aclose()
    resources.http = providers(
        requests,
        openalex=lambda request: httpx.Response(200, json={"results": []}),
        semantic_scholar=lambda request: httpx.Response(404, json={"error": "not found"}),
    )
    return requests


async def uploaded(resources, data):
    """Upload, ingest and look up, and return the paper as the library then holds it."""
    accepted = await ingested(resources, data)
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    return await detail(resources, accepted.paper_id)


def required_fields(paper) -> tuple:
    # A PDF wraps its abstract across lines; wherever the lines break is not part of the value.
    return (paper.title, paper.authors, paper.year, " ".join((paper.abstract or "").split()))


async def test_given_a_pdf_the_parser_can_read_when_uploaded_then_it_needs_no_model(
    resources, model
):
    """Given every field in a form the parser reads, the PDF alone fills the paper."""
    _, calls = model
    await no_provider_match(resources)
    text = f"© 2024 The Authors.\nAbstract\n{ABSTRACT}\nIntroduction\nBody."
    paper = await uploaded(resources, single_column(text, **INFO))
    assert required_fields(paper) == (TITLE, AUTHORS, 2024, ABSTRACT)
    assert calls == []
    for field in ("title", "authors", "year", "abstract"):
        assert paper.metadata_provenance[field] == {"source": "pdf"}, field


async def test_given_a_pdf_without_embedded_authors_when_uploaded_then_the_model_fills_the_gaps(
    resources, model
):
    """Given no embedded details, the fallback reads the printed text and fills what is missing."""
    answer, calls = model
    answer.update(title=TITLE, authors=AUTHORS, year=2023, abstract=ABSTRACT, doi=None)
    await no_provider_match(resources)
    paper = await uploaded(resources, printed_only())
    assert required_fields(paper) == (TITLE, AUTHORS, 2023, ABSTRACT)
    (request,) = calls
    assert "2023" in json.dumps(request["input"]) and BYLINE in json.dumps(request["input"])
    assert paper.metadata_provenance["title"] == {"source": "pdf"}
    for field in ("authors", "year", "abstract"):
        assert paper.metadata_provenance[field]["source"] == "llm", field


@pytest.mark.parametrize(
    ("build", "year"),
    [
        pytest.param(
            embedded_title_and_authors,
            2023,
            id="title-and-authors-embedded",
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="ARA-118: the model is asked only when title or authors are missing, "
                "so a printed year and abstract stay empty.",
            ),
        ),
        pytest.param(
            two_column,
            2026,
            id="two-column",
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="ARA-118: page text interleaves the columns, so the model's abstract "
                "fails the verbatim evidence check and is dropped.",
            ),
        ),
    ],
)
async def test_given_a_printed_year_and_abstract_when_uploaded_then_neither_stays_empty(
    resources, model, build, year
):
    """Given a model that reports what the paper prints, no required field is left empty."""
    answer, _ = model
    answer.update(title=TITLE, authors=AUTHORS, year=year, abstract=ABSTRACT, doi=None)
    await no_provider_match(resources)
    paper = await uploaded(resources, build())
    assert required_fields(paper) == (TITLE, AUTHORS, year, ABSTRACT)
