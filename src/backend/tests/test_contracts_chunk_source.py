"""The chunk source endpoint publishes structured-chunk provenance (ARA-071)."""

from app.main import create_app

PATH = "/api/v1/documents/{document_id}/chunks/{chunk_id}"


def test_chunk_source_response_carries_structured_provenance():
    spec = create_app().openapi()
    content = spec["paths"][PATH]["get"]["responses"]["200"]["content"]
    name = content["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    schemas = spec["components"]["schemas"]
    # Both Citation keys stay stable for the generated frontend types.
    assert name == "app__schemas__research__Citation"
    assert "app__schemas__ai__Citation" in schemas
    properties = schemas[name]["properties"]
    assert {"chunk_id", "document_id", "page", "excerpt"} <= set(properties)
    assert {"page_end", "section", "kind", "bboxes"} <= set(properties)
    assert schemas[name].get("required", []) == ["chunk_id", "document_id", "page", "excerpt"]
    # The new fields are optional, so older clients keep parsing the response.
    assert properties["page_end"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert properties["section"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert properties["kind"]["anyOf"][0]["enum"] == ["front_matter", "text", "table", "references"]
    assert properties["bboxes"]["items"] == {"items": {"type": "number"}, "type": "array"}
