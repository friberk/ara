"""Per-paper reading for windows too small for a comparison's evidence (ARA-094).

docs/plans/retrieval-orchestration.md, step 7: when a comparison or the wider retry wants more
evidence than the ceiling E allows, each answering paper is read in its own call (map), within
the working budget W, and the answer is written from their notes (reduce). This is the
sub-question pattern of LlamaIndex's Sub-Question Query Engine. Notes keep the passages'
handles, so the final answer still cites real chunks and is validated as strictly as any other.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.integrations.context_registry import hosted_reasoning_headroom
from app.integrations.llm import LLMError, reserve
from app.integrations.tokens import keep_head
from app.rag.citations import SOURCE, HandleMap, HandleTransducer
from app.rag.packing import Passage, citable, render_evidence, render_header
from app.services.context import assemble_answer_prompt
from app.services.memory import billed_tokens

NOTES_LABEL = "Notes from each paper's passages (cite their handles)"
NO_NOTES = "These passages do not answer the question."
# A cut note ends before a handle it would split.
OPEN_HANDLE = re.compile(r"\[[^\]]*$")


@dataclass
class PaperNotes:
    """What the map step produced: notes per document, the passages they may cite, and each
    call's usage for the chat meter."""

    notes: list[tuple[str, str]] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    @property
    def citable(self) -> list[Passage]:
        """Only passages the notes cite: the synthesis never saw the others."""
        cited = {identifier for _, text in self.notes for identifier in SOURCE.findall(text)}
        return [item for item in self.passages if str(item.chunk_id) in cited]

    def block(self, counter, headers: dict[str, str], room: int) -> str:
        """The notes under their paper headers, each cut to an equal share of `room`."""
        handles = {str(item.chunk_id): item.handle for item in self.passages}
        parts = []
        share = room // max(1, len(self.notes))
        for document, text in self.notes:
            header = render_header(headers[document])
            body = SOURCE.sub(lambda match: f"[{handles[match[1]]}]", text)
            kept = keep_head(counter, body, max(0, share - counter.count(header) - 2))
            if kept != body:
                kept = OPEN_HANDLE.sub("", kept)
            parts.append(header + kept + "\n")
        return "\n".join(parts)


async def read_papers(
    resources,
    client,
    *,
    model: str,
    effort: str,
    limits,
    evidence,
    papers: dict[str, object],
    questions: dict[str, str],
    room: int,
    slots: Callable,
) -> PaperNotes:
    """One call per answering paper, each within W, with notes sized so all fit `room` (E).

    `papers` maps a document to its PaperHeader and `questions` to the question asked of it.
    """
    answering = evidence.target_papers()
    headers = sum(
        limits.counter.count(render_header(evidence.headers[document])) + 2
        for document in answering
    )
    note_tokens = min(limits.max_output, max(1, (room - headers) // len(answering)))
    target = evidence.evidence_pass.target_tokens // len(answering)
    found = PaperNotes()
    for document in answering:
        chosen: list[Passage] = []

        def block(budget: int, document=document, chosen=chosen) -> str:
            # Handles run on across papers, so the notes' handles never collide.
            first = len(found.passages) + 1
            chosen[:] = evidence.paper_passages(document, min(budget, target), first)
            return render_evidence(chosen)

        assembled = assemble_answer_prompt(
            profile=limits,
            papers=[papers[document]],
            history=[],
            memory_summary=None,
            recalled=[],
            evidence_block=block,
            question=questions[document],
            retrieved_for=None,
        )
        await reserve(resources, model, assembled.usage.input_tokens)
        async with slots():
            result = await client.complete_messages(
                model,
                effort,
                assembled.messages,
                max_output_tokens=note_tokens + hosted_reasoning_headroom(effort),
            )
        allowed = citable(chosen)
        transducer = HandleTransducer(HandleMap(allowed))
        text = transducer.feed(result.content) + transducer.flush()
        if transducer.unknown:
            raise LLMError("UNGROUNDED_OUTPUT", "A paper's notes cited unavailable evidence.")
        found.notes.append((document, NO_NOTES if transducer.insufficient else text.strip()))
        found.passages.extend(allowed)
        found.calls.append({"model": model, **billed_tokens(result.usage)})
    return found
