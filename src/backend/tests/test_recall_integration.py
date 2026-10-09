"""Earlier turns are embedded and recalled by similarity on real PostgreSQL (ARA-077)."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models.jobs import BackgroundJob
from app.models.memory import ChatTurnEmbedding
from app.repositories.jobs import claim
from tests.support.chats import add_turns, seed_chat
from tests.support.papers import OPENAI, QWEN
from tests.support.providers import ollama_fixture, openai_fixture
from tests.support.vectors import fixture_vector

pytestmark = pytest.mark.integration

DATASETS = ("What datasets were used?", "The paper uses Natural Questions and TriviaQA datasets.")


@pytest.fixture
def embedders(resources, monkeypatch):
    """Route turn embeddings to the deterministic provider fixtures."""
    from app.integrations import embeddings
    from app.services import local_models, memory

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    calls = {"openai": [], "ollama": []}

    def fixture_embedder(resources, profile):
        transport = (
            openai_fixture(calls["openai"])
            if profile.provider == "openai"
            else ollama_fixture(calls["ollama"])
        )
        return embeddings.create_embedder(resources, profile, transport=transport)

    @asynccontextmanager
    async def slot(resources, key, **options):
        yield

    monkeypatch.setattr(memory, "create_embedder", fixture_embedder)
    monkeypatch.setattr(local_models, "retrieval_inference_slot", slot)
    return calls


def filler(count: int, start: int = 0):
    return [
        (f"Question {index}: how does recall change?", f"Turn {index}: recall improves steadily.")
        for index in range(start, start + count)
    ]


async def embed_turn(resources, message_id):
    from app.services.memory import enqueue_embed_turn, run_embed_turn_job

    async with resources.sessions() as session, session.begin():
        job = await enqueue_embed_turn(session, message_id)
        job_id, generation, payload = job.id, job.generation, job.payload
    token = await claim(resources.sessions, job_id, generation)
    assert token is not None
    await run_embed_turn_job(resources, job_id, generation, token, payload)
    return job_id, generation, token, payload


async def turn_embeddings(resources, chat_id):
    async with resources.sessions() as session:
        return (
            await session.scalars(
                select(ChatTurnEmbedding).where(ChatTurnEmbedding.session_id == chat_id)
            )
        ).all()


async def load_job(resources, job_id):
    async with resources.sessions() as session:
        return await session.get(BackgroundJob, job_id)


async def test_given_completed_turn_when_embedding_then_q_and_a_use_the_paper_profile(
    resources, embedders
):
    from app.services.memory import run_embed_turn_job

    _, _, chat_id = await seed_chat(resources)
    chunk = uuid4()
    citation = {"chunk_id": str(chunk), "document_id": str(uuid4()), "page": 4, "excerpt": "x"}
    (turn,) = await add_turns(
        resources,
        chat_id,
        [(DATASETS[0], f"It uses Natural Questions [source:{chunk}].", [citation])],
    )
    job_id, generation, token, payload = await embed_turn(resources, turn.answer)
    assert payload == {"message_id": str(turn.answer), "chat_id": str(chat_id)}
    ((request,),) = [call["input"] for call in embedders["openai"]]
    # OpenAI receives flattened text; citations become page references.
    assert request == "Q: What datasets were used? A: It uses Natural Questions (p. 4)."
    (row,) = await turn_embeddings(resources, chat_id)
    assert (row.message_id, row.profile) == (turn.answer, OPENAI)
    job = await load_job(resources, job_id)
    assert (job.kind, job.state, job.result) == ("embed_turn", "completed", {"profile": OPENAI})
    # A redelivery of the finished generation holds no lease and sends nothing.
    await run_embed_turn_job(resources, job_id, generation, token, payload)
    assert len(embedders["openai"]) == 1 and len(await turn_embeddings(resources, chat_id)) == 1


async def test_given_paper_profile_when_embedding_turn_then_local_profile_is_used(
    resources, embedders
):
    _, _, chat_id = await seed_chat(resources, retrieval_profile=QWEN)
    (turn,) = await add_turns(resources, chat_id, [DATASETS])
    await embed_turn(resources, turn.answer)
    (row,) = await turn_embeddings(resources, chat_id)
    assert row.profile == QWEN and len(row.embedding.to_list()) == 2560
    assert embedders["openai"] == [] and len(embedders["ollama"]) == 1


async def test_given_turn_already_queued_when_enqueueing_again_then_one_job(resources):
    from app.services.memory import enqueue_embed_turn

    _, _, chat_id = await seed_chat(resources)
    (turn,) = await add_turns(resources, chat_id, [DATASETS])
    async with resources.sessions() as session, session.begin():
        first = await enqueue_embed_turn(session, turn.answer)
        second = await enqueue_embed_turn(session, turn.answer)
    assert first is not None and second is None
    async with resources.sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "embed_turn")
        )
    assert count == 1


async def test_given_uninstalled_local_profile_when_embedding_turn_then_settles_unavailable(
    resources,
):
    _, _, chat_id = await seed_chat(resources, retrieval_profile=QWEN)
    (turn,) = await add_turns(resources, chat_id, [DATASETS])
    job_id, *_ = await embed_turn(resources, turn.answer)
    job = await load_job(resources, job_id)
    assert (job.state, job.result) == ("completed", {"unavailable": "LOCAL_MODEL_NOT_READY"})
    assert job.attempts == 1 and await turn_embeddings(resources, chat_id) == []


async def test_given_thirty_turns_when_asking_again_then_turn_two_recalled_not_recent_ones(
    resources, embedders
):
    from app.services.memory import recall_turns

    _, _, chat_id = await seed_chat(resources)
    recent_datasets = ("Tell me about the datasets.", "The datasets are described in section 4.")
    turns = await add_turns(
        resources,
        chat_id,
        [*filler(2), DATASETS, *filler(25, start=3), recent_datasets, *filler(1)],
    )
    assert len(turns) == 30
    for turn in turns:
        await embed_turn(resources, turn.answer)
    recent = {turn.answer for turn in turns[-4:]}
    recalled = await recall_turns(
        resources,
        chat_id=chat_id,
        profile=OPENAI,
        query_vector=fixture_vector("which datasets again?", 3072),
        exclude_ids=recent,
    )
    assert recalled == [DATASETS]
    # Without the recent window excluded, the newer datasets turn is recalled too.
    everything = await recall_turns(
        resources,
        chat_id=chat_id,
        profile=OPENAI,
        query_vector=fixture_vector("which datasets again?", 3072),
        exclude_ids=set(),
    )
    assert set(everything) == {DATASETS, recent_datasets}


async def test_given_other_profile_or_chat_when_recalling_then_nothing_leaks(resources, embedders):
    from app.services.memory import recall_turns

    _, _, chat_id = await seed_chat(resources)
    _, _, other_chat = await seed_chat(resources)
    (turn,) = await add_turns(resources, other_chat, [DATASETS])
    await embed_turn(resources, turn.answer)
    vector = fixture_vector("which datasets again?", 3072)
    assert (
        await recall_turns(
            resources, chat_id=chat_id, profile=OPENAI, query_vector=vector, exclude_ids=set()
        )
        == []
    )
    assert (
        await recall_turns(
            resources,
            chat_id=other_chat,
            profile=QWEN,
            query_vector=fixture_vector("which datasets again?", 2560),
            exclude_ids=set(),
        )
        == []
    )


async def test_given_embed_turn_job_when_worker_executes_then_turn_is_embedded(
    resources, embedders, monkeypatch
):
    from app.jobs import actors
    from app.services.memory import enqueue_embed_turn

    monkeypatch.setattr(actors, "_resources", resources)
    _, _, chat_id = await seed_chat(resources)
    (turn,) = await add_turns(resources, chat_id, [DATASETS])
    async with resources.sessions() as session, session.begin():
        job_id = (await enqueue_embed_turn(session, turn.answer)).id
    await actors.execute_job.fn.__wrapped__(str(job_id), 1)
    job = await load_job(resources, job_id)
    assert (job.state, job.result) == ("completed", {"profile": OPENAI})
    assert len(await turn_embeddings(resources, chat_id)) == 1


@pytest.mark.parametrize("chat_is_local", [True, False])
@pytest.mark.parametrize("profile", [OPENAI, QWEN])
def test_given_turn_embedding_policy_then_every_chat_embeds_its_turn_text(chat_is_local, profile):
    from app.integrations.embedding_catalog import embedding_profile
    from app.services.memory import embeds_turn_text

    # User decision (spec §4.6): embeddings follow the paper's profile even for local chats;
    # only generation must stay local.
    assert embeds_turn_text(chat_is_local, embedding_profile(profile)) is True


async def test_given_local_chat_on_hosted_profile_when_embedding_then_turn_text_is_sent(
    resources, embedders
):
    _, _, chat_id = await seed_chat(resources)
    (turn,) = await add_turns(resources, chat_id, [DATASETS], model="ifm-k2-horizon-7b")
    await embed_turn(resources, turn.answer)
    ((sent,),) = [call["input"] for call in embedders["openai"]]
    assert sent == f"Q: {DATASETS[0]} A: {DATASETS[1]}"
    assert [row.profile for row in await turn_embeddings(resources, chat_id)] == [OPENAI]
