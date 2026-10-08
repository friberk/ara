# ARA-032 complete stored citation excerpt

Changed only src/backend/app/routes/documents.py and src/backend/tests/test_research_integration.py. The route now returns chunk.text instead of chunk.text[:1200]. Persisted ingestion chunks are already bounded to 3200 characters, so the response exposes complete selected evidence without introducing an unbounded source read. No migration, main-database mutation, paid inference, or unrelated behavior change.

Regression: test_citation_excerpt_preserves_late_evidence_and_denies_another_document creates two actual documents and a persisted physical-page7 chunk in isolated real PostgreSQL. Supporting threshold evidence occurs after character1200 within a3200-character bound. Actual API response must contain that evidence and the complete exact chunk; requesting the same chunk through the other existing document must return404 CITATION_NOT_FOUND without leaking evidence.

RED command:
docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest tests/test_research_integration.py::test_citation_excerpt_preserves_late_evidence_and_denies_another_document -q
Observed:1failed1.54s; expected supporting text absent from the returned1200-character prefix. /tmp/ara-citation-red.txt.

GREEN full-suite command:
docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest -q
Observed:58passed13.60s, zero skips/failures. Includes the original57 tests plus new regression, with actual PostgreSQL/Redis/MinIO and the existing parser/worker/API checks. Cross-document denial passed. /tmp/ara-citation-green.txt.

Ruff command:
docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps api uv run --frozen ruff check .
Observed:All checks passed, exit0. /tmp/ara-citation-ruff.txt.

No tests in flight; shared testDB is free. Source is stable for root browser recheck and documentation/tracker updates.
