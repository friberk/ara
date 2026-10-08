# Implementation status

The approved plan's core application is integrated into `main`. The user requested retaining `feat/ai-research-assistant`, which remains archived at `526ef68`. All five homework workflows have been exercised through the GUI, including real OpenAlex search and real OpenAI generation. GitHub publication is deferred at the user's request. The student's reflection and Brightspace submission remain separate deliverables.

## Milestones

| Phase | Status | Delivered evidence |
| --- | --- | --- |
| 0 — Foundation | Complete | Six Compose services, migration/bucket gates, pinned images and lockfiles, private configuration, durable worker canary, restart persistence and source reload. |
| 1 — Search/library | Complete | Both provider adapters, normalized pagination/errors, canonical save, DOI deduplication and persistent library. |
| 2 — PDF ingestion | Complete | Private originals in MinIO, bounded child-process extraction, page-aware chunks, metadata/provenance/editor and durable status/recovery. |
| 3 — Summaries/chat | Complete | Hosted Responses integration, complete-text summary jobs, lexical retrieval, persistent multi-turn SSE chat, scoped citations, model settings and cost reservations. |
| 4 — Enhancements | Deferred | Automatic open-access downloads, semantic retrieval, local serving and OCR remain outside the verified core. Targeted interface corrections are complete. |
| 5 — Verification/submission | Application checks complete; submission pending | Automated and live checks, local demo recording, README, license notices, prepared CI, issue records and authentic agent evidence. No remote CI run or Brightspace submission claimed. |

## Ownership and integration

The backend agent owned database models, migrations, research routes and ingestion. The AI agent owned generation, retrieval and conversation modules against frozen contracts. The frontend agent owned React components and generated API types. Infrastructure and skill agents owned disjoint files. The lead supplied fixtures, browser tests, documentation and integration checks. An independent reviewer identified five defects; their owners reproduced and corrected them, and the reviewer subsequently confirmed those five resolutions.

Shared database tests ran serially in `ara-test`. Browser scenarios used `ara-e2e` with real PostgreSQL/Redis/MinIO and deterministic external HTTP fixtures. The live demonstration used the ordinary development stack. These projects have separate persistent volumes.

## Verification and limits

See [final verification](verification-final.md) for commands, counts and live observations. The original [foundation evidence](verification-phase0.md) and delegated reports preserve intermediate results; their earlier pending items are superseded by this status record.

Semantic Scholar's live anonymous request returned a handled rate limit; its successful adapter/UI behavior is verified with external HTTP fixtures. All three hosted model IDs were listed by the configured account, while paid generation was exercised with Luna/low. Lexical retrieval and citation identity checks do not guarantee that every generated claim follows from its cited text.

Deadline: October 10, 11:59 PM, with a planned 10 PM submission target. Preserve time for the student's own reflection, screenshots and final submission review. Deferred features must not displace those deliverables.
