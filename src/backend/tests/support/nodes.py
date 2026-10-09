"""Fused retrieval candidates shaped like `app.rag.retrievers.chunk_node` output."""

from llama_index.core.schema import NodeWithScore, TextNode


def node(index: int, text: str, *, section: str | None = "Results", page: int = 3):
    return NodeWithScore(
        node=TextNode(
            id_=f"00000000-0000-0000-0000-{index:012d}",
            text=text,
            metadata={
                "page": page,
                "page_end": page,
                "section": section,
                "kind": "text",
                "ordinal": index,
            },
        ),
        score=1 / (60 + index),
    )
