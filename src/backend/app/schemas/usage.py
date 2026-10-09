"""The chat's context and cost meter (ARA-085)."""

from pydantic import BaseModel


class ChatContext(BaseModel):
    # Tokens the latest completed answer sent, as counted when its prompt was assembled.
    used_tokens: int | None
    # The selected model's input budget in this app, which is what bounds the conversation.
    input_budget: int
    # The model's full window; larger than the budget when the app works in a smaller cap.
    window: int
    model: str


class ChatCost(BaseModel):
    """USD as decimal strings priced from the catalogs. Only recorded calls count."""

    total: str
    answers: str
    planning: str
    compaction: str
    embeddings: str
    reranking: str
    # Every recorded call ran on a local model.
    local: bool
    # Completed answers from before usage was recorded; their cost is not in the total.
    unrecorded_turns: int


class ChatUsage(BaseModel):
    context: ChatContext
    cost: ChatCost
