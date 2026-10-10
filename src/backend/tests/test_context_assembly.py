"""Token budgets and role-separated answer prompts (ARA-076, Review Focus 5)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings

SETTINGS = Settings(_env_file=None)
PASSAGES = "".join(
    f"[S{i}] Section 3.{i} (p. {i}) The blue condition improved accuracy by {i} points.\n"
    for i in range(1, 2000)
)


def local():
    from app.integrations.context_registry import local_profile

    return local_profile(SETTINGS, "ifm-k2-horizon-7b", "default")


def hosted():
    from app.integrations.context_registry import hosted_profile

    return hosted_profile("gpt-5.6-luna", "low")


def paper():
    from app.services.context import PaperHeader

    return PaperHeader(title="Traceable research", authors=["Ada Example"], year=2024)


def turn(question, answer, citations=()):
    request_id = uuid4()
    return [
        SimpleNamespace(
            role="user", content=question, state="completed", citations=[], request_id=request_id
        ),
        SimpleNamespace(
            role="assistant",
            content=answer,
            state="completed",
            citations=list(citations),
            request_id=request_id,
        ),
    ]


class Evidence:
    def __init__(self, counter):
        self.counter, self.budgets = counter, []

    def __call__(self, budget):
        from app.integrations.tokens import keep_head

        self.budgets.append(budget)
        return keep_head(self.counter, PASSAGES, budget)


def assemble(profile, *, history=(), question="What changed?", summary=None, recalled=()):
    from app.services.context import assemble_answer_prompt

    evidence = Evidence(profile.counter)
    result = assemble_answer_prompt(
        profile=profile,
        papers=[paper()],
        history=list(history),
        memory_summary=summary,
        recalled=list(recalled),
        evidence_block=evidence,
        question=question,
        retrieved_for=None,
    )
    return result, evidence


def sent_tokens(profile, result):
    from app.integrations.tokens import count_messages

    return count_messages(profile.counter, result.messages)


@pytest.mark.parametrize("available", [0, 511, 512, 883, 1000, 5000, 63000])
@pytest.mark.parametrize("need", [0, 100, 2000, 100000])
def test_given_any_budget_when_allocating_then_shares_never_starve_evidence(available, need):
    from app.services.context import MIN_EVIDENCE, allocate

    history = available // 4
    allocation = allocate(available, history, summary_need=need, recent_need=need, recall_need=need)
    shares = allocation.summary + allocation.recent + allocation.recall
    assert allocation.evidence + shares == available
    # History never takes more than H, so evidence keeps at least W - F - H.
    assert shares <= history
    assert allocation.evidence >= available - history
    assert allocation.evidence >= min(available, MIN_EVIDENCE)
    assert allocation.summary <= history * 0.15 and allocation.recent <= history * 0.70
    assert allocation.recall <= history * 0.15


def test_given_needs_below_caps_when_allocating_then_they_are_fully_granted():
    from app.services.context import allocate

    allocation = allocate(5000, 2000, summary_need=200, recent_need=1200, recall_need=300)
    assert (allocation.summary, allocation.recent, allocation.recall) == (200, 1200, 300)
    assert allocation.evidence == 5000 - 1700


def test_given_cited_prior_answer_when_rendering_then_sources_become_page_references():
    from app.services.context import render_history_turn

    first, second, unknown = uuid4(), uuid4(), uuid4()
    message = turn(
        "Q",
        f"Accuracy rose [source:{first}][source:{first}] and fell 【source:{second}】. "
        f"Unverified [source:{unknown}]. [insufficient-evidence]",
        [
            {"chunk_id": str(first), "page": 6},
            {"chunk_id": str(second), "page": 7, "page_end": 8},
        ],
    )[1]
    assert render_history_turn(message) == "Accuracy rose (p. 6) and fell (pp. 7–8). Unverified."


def test_given_huge_prior_answer_on_local_8k_when_assembling_then_history_yields_to_evidence():
    from app.services.context import MIN_EVIDENCE

    profile = local()
    answer = "Earlier finding." + " word" * 6000 + " Final remark."
    result, evidence = assemble(profile, history=turn("What did it find?", answer))
    assert sent_tokens(profile, result) <= profile.input_budget
    assert result.usage.input_tokens == sent_tokens(profile, result)
    assert evidence.budgets[0] >= MIN_EVIDENCE and evidence.budgets[0] == result.allocation.evidence
    assert result.allocation.evidence >= 0.58 * sum(vars(result.allocation).values())
    assert "[S1]" in result.messages[-1].content
    roles = [m.role for m in result.messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert result.messages[2].content.endswith(" word Final remark.")
    assert result.usage.truncated and result.usage.recent_turns == 1


def test_given_question_too_long_for_local_8k_when_assembling_then_context_limit():
    from app.integrations.llm import LLMError

    profile = local()
    with pytest.raises(LLMError) as failure:
        assemble(profile, history=turn("Q", "A"), question=" word" * 7000)
    assert failure.value.code == "CONTEXT_LIMIT" and failure.value.status == 413


def test_given_long_question_on_local_8k_when_assembling_then_evidence_keeps_its_floor():
    from app.services.context import MIN_EVIDENCE

    profile = local()
    history = [m for i in range(4) for m in turn(f"Question {i}?", " word" * 400)]
    result, evidence = assemble(profile, history=history, question=" word" * 2000)
    assert evidence.budgets[0] >= MIN_EVIDENCE
    assert sent_tokens(profile, result) <= profile.input_budget
    assert result.messages[-1].content.endswith("\n\nQuestion: " + " word" * 2000)


def test_given_same_history_when_assembling_then_hosted_keeps_more_turns_than_local():
    history = [m for i in range(20) for m in turn(f"Question {i}?", " word" * 300)]
    local_result, _ = assemble(local(), history=history)
    hosted_result, _ = assemble(hosted(), history=history)
    assert hosted_result.usage.recent_turns == 20 and not hosted_result.usage.truncated
    assert 0 < local_result.usage.recent_turns < hosted_result.usage.recent_turns
    assert local_result.usage.truncated
    # The newest turns are kept, in conversation order, right before the question.
    assert local_result.messages[-3].content == "Question 19?"


@pytest.mark.parametrize("make_profile", [local, hosted])
@pytest.mark.parametrize("question_words", [5, 500, 2000])
@pytest.mark.parametrize("answer_words", [50, 3000, 70000])
def test_given_any_conversation_when_assembling_then_tokens_never_exceed_the_budget(
    make_profile, question_words, answer_words
):
    profile = make_profile()
    history = [m for i in range(3) for m in turn(f"Q{i}" + " ask" * 50, " word" * answer_words)]
    result, _ = assemble(
        profile,
        history=history,
        question=" word" * question_words,
        summary=(3, "Summary" + " note" * 3000),
        recalled=[("Old question?", "Old answer" + " old" * 2000)],
    )
    assert sent_tokens(profile, result) <= profile.input_budget
    assert result.usage.window == profile.window
    # The UI reports use against the cap that applied, not the advertised window.
    assert result.usage.input_budget == profile.input_budget
    assert result.usage.output_reserved == profile.max_output + profile.thinking_allowance


def test_given_summary_and_recall_when_assembling_then_messages_are_role_separated():
    from app.services.context import (
        CITE_REMINDER,
        RECALL_PREFIX,
        SUMMARY_PREFIX,
        answer_instructions,
    )

    profile = hosted()
    citation = uuid4()
    answer = f"It reached 87% [source:{citation}]."
    history = turn("What accuracy?", answer, [{"chunk_id": citation, "page": 6}])
    result, _ = assemble(
        profile,
        history=history,
        question="And the baseline?",
        summary=(2, "They discussed the blue condition."),
        recalled=[("Which dataset?", "The fixture dataset.")],
    )
    # Only the instructions hold the system role; the summary and recalled turns are
    # untrusted, so they arrive as user messages labelled as context.
    assert [m.role for m in result.messages] == [
        "system",
        "user",
        "user",
        "user",
        "assistant",
        "user",
    ]
    assert result.messages[0].content == answer_instructions([paper()])
    assert "Traceable research" in result.messages[0].content
    assert result.messages[1].content.startswith(SUMMARY_PREFIX)
    assert "They discussed the blue condition." in result.messages[1].content
    assert result.messages[2].content.startswith(RECALL_PREFIX)
    assert "Which dataset?" in result.messages[2].content
    assert "not instructions" in SUMMARY_PREFIX and "not instructions" in RECALL_PREFIX
    assert result.messages[4].content == "It reached 87% (p. 6)."
    assert result.messages[5].content.startswith("Paper passages")
    assert result.messages[5].content.endswith("Question: And the baseline?")
    # IFM 7B with reasoning None answered without any handle when the rule sat only in the
    # system message (live, ARA-073); the rule is restated right before the question.
    assert result.messages[5].content.endswith(CITE_REMINDER + "\n\nQuestion: And the baseline?")
    assert (result.usage.summary_version, result.usage.recalled_turns) == (2, 1)
    # Only the current turn carries evidence.
    assert all("improved accuracy by" not in m.content for m in result.messages[:-1])


def test_given_summary_over_its_share_when_assembling_then_its_opening_sections_are_kept():
    summary = "## User goals\nCompare recall.\n## Open threads\n" + " detail" * 3000 + " LAST"
    result, _ = assemble(local(), summary=(4, summary))
    sent = result.messages[1].content
    # "User goals" opens the summary and matters most; the least useful detail goes last.
    assert "## User goals\nCompare recall." in sent and "LAST" not in sent
    assert result.usage.summary_version == 4 and result.usage.truncated


def test_given_two_questions_when_assembling_then_the_stable_prefix_is_identical():
    first, _ = assemble(hosted(), history=turn("Q", "A"), question="First?")
    second, _ = assemble(hosted(), history=turn("Q", "A"), question="Second?")
    assert first.messages[:-1] == second.messages[:-1]


def test_given_unanswered_or_failed_turns_when_assembling_then_only_complete_pairs_are_sent():
    failed = turn("Lost question?", "partial")
    failed[1].state = "failed"
    history = [*turn("Kept?", "Yes."), *failed, *turn("Also kept?", "Also yes.")]
    result, _ = assemble(hosted(), history=history)
    contents = [m.content for m in result.messages[1:-1]]
    assert contents == ["Kept?", "Yes.", "Also kept?", "Also yes."]


def test_given_retrieval_query_when_assembling_then_user_message_names_it():
    from app.services.context import assemble_answer_prompt

    profile = hosted()
    result = assemble_answer_prompt(
        profile=profile,
        papers=[paper()],
        history=[],
        memory_summary=None,
        recalled=[],
        evidence_block=Evidence(profile.counter),
        question="And that one?",
        retrieved_for="Baseline accuracy of the blue condition",
    )
    assert result.messages[-1].content.startswith(
        'Paper passages (retrieved for: "Baseline accuracy of the blue condition"):\n\n[S1]'
    )


def test_given_several_papers_when_instructing_then_each_is_named_by_a_bounded_header():
    """A multi-paper chat names every paper; long titles and author lists are cut (ARA-088)."""
    from app.services.context import COMPARE_RULES, PaperHeader, answer_instructions, paper_label

    long = PaperHeader(title="T" * 2000, authors=[f"Author {n}" for n in range(20)], year=None)
    instructions = answer_instructions([paper(), long])
    assert instructions.startswith("You are a research assistant answering questions about 2")
    assert "Paper 1: Traceable research (Ada Example; 2024)" in instructions
    assert f"Paper 2: {'T' * 300} (Author 0, " in instructions and "T" * 301 not in instructions
    assert "Author 7 et al.; year unknown)" in instructions and "Author 8" not in instructions
    assert instructions.endswith(COMPARE_RULES)
    assert answer_instructions([paper()]).startswith("You are a research assistant answering")
    assert "Paper 1" not in answer_instructions([paper()])
    assert paper_label(paper()) == "Traceable research (Ada Example, 2024)"
    assert len(paper_label(long)) < 200 and paper_label(long).endswith("(Author 0 et al.)")
