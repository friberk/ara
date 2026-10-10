"""Short `[S#]` passage handles, their stream transducer and the insufficient-evidence sentinel.

Models cite passages as `[S1]`; clients and storage only see canonical `[source:<chunk-uuid>]`
markers (ARA-073). The transducer maps handles while text streams and never emits half a marker.
"""

import re
from collections.abc import Collection, Sequence
from uuid import UUID

from app.rag.packing import Passage
from app.schemas.ai import Citation

INSUFFICIENT = "[insufficient-evidence]"
# A bracket tail stays held only while it can still become a handle group or the sentinel.
HOLD_LIMIT = 40
HANDLE = re.compile(r"S(\d{1,4})", re.I)
GROUP = re.compile(r"[\[【]\s*(S\d{1,4}(?:\s*[,;]\s*S\d{1,4})*)\s*[\]】]", re.I)
OPEN_GROUP = re.compile(r"[\[【]\s*(?:S\d*(?:\s*[,;]\s*(?:S\d*)?)*)?", re.I)
SENTINEL = re.compile(r"[\[【]insufficient-evidence[\]】][ \t]*", re.I)
SENTINEL_AT_END = re.compile(SENTINEL.pattern + r"$", re.I)
FENCE = "```"
SOURCE = re.compile(r"\[source:([^\]]+)\]")
UNICODE_SOURCE = re.compile(r"【source:([^】]*)】")
SOURCE_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def handle_key(handle: str) -> str | None:
    match = HANDLE.fullmatch(handle.strip())
    return f"S{int(match[1])}" if match else None


class HandleMap:
    def __init__(self, passages: Sequence[Passage]):
        self.passages = {handle_key(item.handle): item for item in passages}

    def resolve(self, handle: str) -> Passage | None:
        return self.passages.get(handle_key(handle))


class HandleTransducer:
    """Feed model deltas; emit text with `[S#]`, `【S#】` and `[S1, S3]` mapped to source markers.

    Unknown handles stay as written and are recorded in `unknown`. The sentinel is removed and
    sets `insufficient`. Text inside fenced code blocks passes through unchanged.
    """

    def __init__(self, handles: HandleMap):
        self.handles = handles
        self.unknown: set[str] = set()
        self.insufficient = False
        self.pending = ""
        self.in_code = False
        self.trim = False

    def feed(self, delta: str) -> str:
        self.pending += delta
        cut = self.safe_length(self.pending)
        ready, self.pending = self.pending[:cut], self.pending[cut:]
        return self.convert(ready)

    def flush(self) -> str:
        ready, self.pending = self.pending, ""
        return self.convert(ready)

    def safe_length(self, text: str) -> int:
        end = len(text)
        # One or two trailing backticks may still become a code fence.
        if 0 < end - len(text.rstrip("`")) < len(FENCE):
            end = len(text.rstrip("`"))
        start = max(text.rfind("[", 0, end), text.rfind("【", 0, end))
        if start >= 0 and end - start <= HOLD_LIMIT and self.could_open(text[start:end]):
            return start
        return end

    @staticmethod
    def could_open(tail: str) -> bool:
        sentinel = "[" + tail[1:].lower()
        return OPEN_GROUP.fullmatch(tail) is not None or (
            len(sentinel) < len(INSUFFICIENT) and INSUFFICIENT.startswith(sentinel)
        )

    def convert(self, text: str) -> str:
        pieces = []
        for index, part in enumerate(text.split(FENCE)):
            if index:
                self.in_code = not self.in_code
                pieces.append(FENCE)
            pieces.append(part if self.in_code else self.map(part))
        return "".join(pieces)

    def map(self, text: str) -> str:
        if self.trim:
            text = text.lstrip(" \t")
            self.trim = not text
        mapped, removed = SENTINEL.subn("", text)
        if removed:
            self.insufficient = True
            # Spaces after a sentinel that ends this piece arrive with the next delta.
            self.trim = SENTINEL_AT_END.search(text) is not None
        return GROUP.sub(self.replace, mapped)

    def replace(self, match: re.Match) -> str:
        handles = HANDLE.findall(match[1])
        found = [self.handles.resolve("S" + number) for number in handles]
        missing = {handle_key("S" + n) for n, item in zip(handles, found, strict=True) if not item}
        if missing:
            self.unknown |= missing
            return match[0]
        return "".join(f"[source:{item.chunk_id}]" for item in found)


def normalize_source_markers(content: str) -> str:
    """Canonicalize the observed wrapper without changing source IDs or case."""

    def replace(match: re.Match) -> str:
        identifier = match.group(1)
        if SOURCE_UUID.fullmatch(identifier) is None:
            raise ValueError("The model returned a malformed source marker.")
        return f"[source:{identifier}]"

    return UNICODE_SOURCE.sub(replace, content)


def passage_citations(
    content: str, passages: Sequence[Passage], document_ids: Collection[UUID]
) -> list[Citation]:
    """Citations in first-cited order; any source outside the supplied passages of the chat's
    documents (one per included paper, ARA-088) is an error."""
    content = normalize_source_markers(content)
    supplied = {str(item.chunk_id): item for item in passages if item.document_id in document_ids}
    citations, seen = [], set()
    for identifier in SOURCE.findall(content):
        if identifier not in supplied:
            raise ValueError("The model cited a source outside the supplied document evidence.")
        if identifier in seen:
            continue
        seen.add(identifier)
        item = supplied[identifier]
        citations.append(
            Citation(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                page=item.page,
                page_end=item.page_end,
                section=item.section or None,
                kind=item.kind,
                bboxes=item.bboxes,
                excerpt=item.text,
            )
        )
    return citations
