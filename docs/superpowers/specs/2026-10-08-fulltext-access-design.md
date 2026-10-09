# ARA-019: PDF retrieval and access information

Status: proposed design for implementation-plan review. The user requested this plan after discussing OpenAlex, Semantic Scholar, university access, and browser fallback. No application implementation is authorized by this document alone.

## Intent and scope

Let a researcher save a paper, retrieve a supported PDF without uploading it manually, and understand what to try when retrieval fails. Support both existing academic providers. Prefer reported open copies, but allow downloading a provider-supplied publisher PDF when the backend's current network grants access. Explain authentication requirements, blocked requests, missing links, and temporary failures without treating every failure as a paywall.

This plan follows the recommended backend/network-retry approach discussed in chat. Users can open Semantic Scholar or a publisher, use institutional sign-in there, download the PDF, and upload it. A browser extension, credential storage, institutional SSO integration, and arbitrary webpage scraping are outside this feature. Browser authentication is not transferred to the backend. Local campus/VPN retry can help only when the downloader's network and the institution's subscription permit access; a remote backend does not inherit the browser computer's network.

## Workspace and ownership

- Worktree: `/Users/bcakar/orca/workspaces/hw1/ara-019-fulltext`.
- Branch: `ara-019-fulltext`, created through Orca from `feat/managed-ollama` commit `ddced814df3de60cd05e926b5a91915360ff2470`, rather than `main`.
- The local-model worktree contained additional uncommitted ARA-053 readiness work at creation. It was inspected read-only and was not copied, stashed, committed, or edited.
- Incorporate later committed `feat/managed-ollama` work before allocating the migration revision and again before final verification. Preserve its runtime, generation, model-preparation, and Activity behavior.
- ARA-019 has one implementation owner for its migration and generated OpenAPI contracts. Track subtasks within ARA-019 rather than allocating IDs that might collide with the other agent.
- Tests, images, ports, and data volumes must be isolated from the other agent's development and test stacks. No GitHub push or merge into `main` is part of this plan.

## Provider discovery

Extend `SearchResult` additively, keeping `pdf_url`, `external_url`, and old persisted snapshots valid:

- `is_open_access: bool | null = null`.
- `locations: list[FullTextLocation] = []`.
- `FullTextLocation`: nullable `pdf_url`, `landing_page_url`, `is_oa`, `license`, and `version`; `host_type` is `publisher`, `repository`, or `unknown`.

For OpenAlex preserve `primary_location`, `best_oa_location`, and `locations`, with stable deduplication. Preserve reported versions, such as accepted manuscripts or submitted preprints; display them when known. For Semantic Scholar request `isOpenAccess` in addition to the current fields and preserve `openAccessPdf.url`, `status`, and `license`; keep status as provider metadata rather than interpreting an OA category as an HTTP outcome. Add nullable `oa_status` to the location for this purpose. Its `url` is a Semantic Scholar record, not a verified publisher download URL.

On an explicit retrieval request, refresh each saved provider identity and use exact normalized DOI lookup against the other provider when a DOI is available. Verify returned DOI equality before accepting cross-provider candidates. Do not infer identity from title similarity, automatically create another library paper, or overwrite manual bibliographic edits. A provider error preserves stored candidates and produces a discovery warning, rather than preventing those candidates from being tried. Discovery enriches source snapshots on the same paper only after existing source/DOI identity checks succeed.

Rank direct PDF candidates: reported OA first; published then accepted then submitted versions when known; stable provider order and URL order break ties. Unknown and non-OA publisher candidates remain eligible after OA candidates. Deduplicate equivalent URLs, preserve query strings needed for downloads, and remove fragments. Try at most 8 candidates per job. Refresh at most the two configured providers, with a 45-second combined discovery deadline. Provider/API requests and PDF requests use separate clients and never share credentials.

Metadata-only browsing and saving must never trigger PDF downloads. `is_open_access = false`, a missing PDF URL, or an absent OA location does not by itself mean that a paywall was observed.

## Public API

All paths are under `/api/v1`.

- `GET /papers/{paper_id}/fulltext` returns `FullTextStatus` without external network calls. It contains `paper_id`, `availability` (`open_copy_reported`, `publisher_link_only`, `unknown`), normalized `locations`, nullable `retrieval_job: JobStatus`, nullable `document_id`, nullable `ingest_job_id`, nullable `last_checked_at`, and bounded `attempts` for the latest retrieval job. Each attempt contains provider, a source label, nullable version/OA/license metadata, nullable HTTP status, outcome, and safe user-facing reason. Detailed candidate URLs stay in normalized locations; raw HTML, cookies, and authentication data are never returned.
- `POST /papers/{paper_id}/retrieve-fulltext` accepts exactly `{request_id: UUID}` and returns 202 `FullTextAccepted {paper_id: UUID, job_id: UUID}`. No URL, browser metadata, or credential fields are accepted.
- A replayed UUID returns its original job, even after failure or a later request. Reusing that UUID for another paper returns 409 `FULLTEXT_REQUEST_CONFLICT`.
- Concurrent fresh requests for a paper with an active retrieval return the same job and persist both request bindings. A fresh UUID after a terminal outcome creates a new job, refreshes candidates, and retries access. No permanent negative cache blocks campus/VPN retries.
- Missing paper: 404 `PAPER_NOT_FOUND`. The existing origin restrictions apply.
- Extend `/jobs` kind and paper filters/linking for `fulltext`. Network retry starts a fresh full-text request; generic `/jobs/{id}/retry` rejects fulltext with 409 `NEW_FULLTEXT_REQUEST_REQUIRED`. Ingestion retry keeps its existing semantics.

Do not add full-text status to every library detail response: the separate endpoint keeps the library path cheap. Derive status from persisted snapshots, requests, attempts, and jobs.

## Durable records and jobs

Add Alembic-owned `fulltext_requests` and `fulltext_attempts` tables. Allocate the next revision after the latest committed local-model migration; the observed head at branch creation was `0005_local_models`.

- `FullTextRequest`: UUID `request_id` primary key; paper FK; job FK; UTC `created_at`. Multiple UUIDs may reference the same active job. Deleting a paper cascades its request records.
- `FullTextAttempt`: UUID ID; job FK; generation; ordinal; provider; candidate JSON snapshot; nullable response status; outcome; bounded safe reason; UTC checked timestamp. Unique `(job_id, generation, ordinal)`. Attempts include failed candidates before a later successful candidate, and are not overwritten during crash recovery.
- Job kind: `fulltext`; payload contains paper ID and `expected_active_document_id` captured under a paper row lock. Checkpoints add generated attachment UUID, discovered candidates, current ordinal, and accepted document/ingest references. Keep payloads bounded.
- Stage names: `discovering_fulltext`, `fetching_pdf`, `storing_pdf`, `retry_wait`, `completed`, `failed`. Progress is stage progress, not invented download percentages.
- Successful PDF storage completes the retrieval job with `outcome: downloaded`, `document_id`, and `ingest_job_id`. Extraction is a separate existing ingest job; retrieval completion does not mean the PDF is ready for analysis.
- If a ready, uploading, or processing document already exists, do not replace it or perform a network download. Complete with `outcome: already_attached` and the current references. A failed document may be replaced through retrieval, subject to the same attachment guard.
- A manual upload that changes the active document after enqueue supersedes retrieval. Complete with `outcome: superseded` and current references; never overwrite the user's newer attachment or historical chat/summary document bindings.

The default worker executes fulltext work independently of local-model admission. Reuse PostgreSQL outbox, three-attempt crash recovery, 60-second leases, 10-second heartbeat, and generation/token fencing. Each task and heartbeat owns its session. Stop fetching when ownership is lost; check fencing again before attachment and terminal writes. Generic job recovery remains authoritative, including failures not raised by the PDF downloader.

## Download boundary

Use a dedicated process/event-loop-owned HTTPX client, with TLS verification on, redirects handled manually, proxy environment inheritance off, and no provider API keys, browser cookies, Authorization, or Referer. Preserve OS/VPN routing. Each request resolves and validates the destination, connects to one validated literal IP, retains the original HTTP Host and TLS hostname through HTTPX's `sni_hostname` extension, and has no reusable connection pool across different original hosts. Checking DNS and then requesting the original hostname is insufficient because it allows a second lookup. Pinning must be tested with real TLS/hostname verification, not only mocked headers.

Constants:

- PDF maximum: `25 * 1024 * 1024` bytes; enforce claimed length and streamed/decompressed bytes.
- Candidate deadline: 45 seconds, including DNS and redirects; connect/pool deadline 5 seconds; read/write deadline 10 seconds; job discovery-plus-fetch deadline 420 seconds.
- Redirect maximum: 5 hops; validate every hop and resolve relative redirects against the original URL, not the pinned IP URL.
- Non-PDF classification body maximum: 64 KiB; no unbounded HTML parsing.
- Schemes/ports: HTTPS 443 and HTTP 80; reject HTTPS-to-HTTP downgrade.
- Reject userinfo, IP-literal URLs, malformed or oversized URLs (more than 4096 characters), disallowed hosts, and all non-global DNS answers (including mixed public/private results, IPv4-mapped IPv6, loopback, link-local, metadata IPs, private networks, and shared address space).
- Accept PDF/octet-stream/absent content type only when the first 1024 bytes satisfy the existing `%PDF-` signature rule. Reject an HTML/login response even when HTTP status is 200 or the content type claims PDF. No PDF parsing runs on the API event loop.

`FULLTEXT_ALLOWED_HOSTS` is an administrator-configured list of exact hostnames, normalized to lowercase IDNA; no wildcards or arbitrary browser override. Initial defaults: `arxiv.org`, `export.arxiv.org`, `aclanthology.org`, `pmc.ncbi.nlm.nih.gov`, `europepmc.org`, `proceedings.neurips.cc`, `openaccess.thecvf.com`, `pdfs.semanticscholar.org`, `link.springer.com`, `www.nature.com`, `nature.com`, `static-content.springer-cdn.com`, `ieeexplore.ieee.org`, `dl.acm.org`. Hosts absent from the list retain browser/upload fallback and report `unsupported_source`. This is support for provider-supplied direct PDF links; it is not a promise to scrape every publisher page or follow arbitrary identity-provider pages.

Test transports/resolvers are injected through ordinary constructor/resource-factory seams. The production downloader never enables private destinations automatically because `APP_ENV=test`. Test-only local fixture behavior belongs in `tests/fixtures`, not a production bypass.

## Outcomes and retry policy

Per-candidate outcomes: `downloaded`, `access_required`, `blocked`, `not_found`, `rate_limited`, `unavailable`, `invalid_pdf`, `unsafe_url`, `unsupported_source`. Overall outcomes additionally include `no_pdf_link`, `already_attached`, and `superseded`.

- HTTP 401 or an explicitly recognized login redirect: `access_required`. Recognize only a terminal path `/login`, `/signin`, or `/Shibboleth.sso/Login`; record the reason without requesting the login destination or claiming entitlement. Ordinary unknown redirects still undergo destination validation.
- HTTP 403: `blocked`. Do not infer paywall, CAPTCHA, or subscription status from it.
- HTTP 404/410: `not_found`.
- HTTP 429: `rate_limited`; record bounded Retry-After (maximum 300 seconds) and try other candidates. When every usable candidate is rate limited/transient, stop this user attempt with an actionable retry time, rather than occupying the worker with sleep.
- Timeout/network/5xx: `unavailable`; try other candidates. Finish the user attempt after the bounded candidate pass. Explicit retrieval failures do not automatically repeat access denials; infrastructure crashes/storage failures retain the existing bounded durable-recovery rules.
- HTTP 200 HTML: `invalid_pdf`, with “The link returned a web page instead of a PDF.” No generic HTML keyword classifier calls this a paywall.
- No direct PDF candidates: `no_pdf_link`, keeping record/publisher links available.

When multiple candidates fail, preserve every attempt and choose the summary reason by priority: `access_required`, `blocked`, `rate_limited`, `unavailable`, `invalid_pdf`, `not_found`, `unsupported_source`, `unsafe_url`, `no_pdf_link`. A successful candidate always wins. If metadata discovery failed and no stored candidate exists, report `unavailable` with the provider failure rather than claiming no copy exists.

## Attachment and version provenance

Extract a shared byte-ingestion entrypoint from the upload service. Retain existing SHA/UUID deduplication, cross-paper reconciliation, storage-failure recovery, original retention, delayed ingest outbox, and metadata correction behavior. Fulltext calls it with an attachment guard carrying retrieval job ID, generation, lease token, and expected active document ID. Guard checks and the active-document write occur together under locks. Manual upload also takes the paper lock, so a retrieval cannot overwrite a concurrent upload.

Use a stable attachment UUID checkpointed before storing bytes. A crash after document/outbox creation reuses accepted references and never redownloads or creates a second document. Missing/stale lease cannot attach. External S3 writes cannot be made transactionally exactly once; the existing deterministic key/grace/recovery approach must remain safe under repeated writes and storage failure.

Add nullable `Document.acquisition` JSON metadata: acquisition method, provider, candidate URL, final URL, observed OA/license/version, timestamp, and retrieval job ID. Old/manual records remain valid. Return nullable acquisition metadata through `FullTextStatus` so the UI can name the retrieved version. Do not overwrite metadata provenance with unverified browser information.

## UI

Use the existing neutral shadcn controls, inline errors, reader gate, Details PDF section, and Activity list.

- Search results show reported open-copy information without fetching it. Missing metadata remains unknown. Keep saving/search-provider switching behavior and cached saved-hit updates.
- In the reader gate and Details PDF section, offer **Get PDF** for papers with known direct candidates, **Find PDF** when provider/DOI lookup can discover candidates, and the existing **Upload PDF** path.
- Active retrieval shows its stage and explains that it continues in the background. Poll only active jobs, refetch on mount/focus, and restore progress after navigation/refresh from persisted state.
- Successful retrieval transitions to the existing ingest progress, then the reader. Do not enable summary/chat before extraction completes.
- `access_required`: “This source requires authentication. Your university may provide access.”
- `blocked`: “This site blocked the download. Institutional access or downloading in your browser may help.”
- Network guidance: “If your university provides access, connect to its network or supported VPN and retry. The app downloads using the network of the computer running its backend.”
- Offer **Retry download**, **Open Semantic Scholar** when available, **Open publisher** through verified OpenAlex publisher location or DOI link, and **Upload PDF**. Links open in a new tab and retain the existing safe-URL handling.
- Retry creates one fresh request UUID per deliberate click; a transport retry retains that UUID. Never auto-retry because focus changed or a VPN might have changed.
- Distinguish retrieval failure from PDF-processing failure. Activity rows link to the correct paper and expose the appropriate action; retain model preparation/download labels supplied by upstream ARA-053.
- Show known acquisition version/license/source near PDF details; do not claim a submitted version is the publisher's final article.
- Keyboard/touch actions, wrapping at 390px, and restrained live-region stage announcements follow existing accessibility patterns. No desktop notification or network-detection subsystem is required.

## Acceptance criteria

1. Given a saved OpenAlex or Semantic Scholar paper with a supported open PDF, when Get PDF is chosen, then the original is retained, extraction completes, and content-grounded summary/Q&A cite that document.
2. Given no Semantic Scholar open PDF, when exact DOI discovery finds an OpenAlex copy, then it attaches to the same saved paper and preserves source/version provenance.
3. Given an authentication-required or blocked source, when retrieval fails, then the UI reports the observed barrier, retains paper metadata, and offers network retry and browser/upload actions.
4. Given a failed access attempt, when a fresh request is made and the same source now returns PDF bytes, then retrieval succeeds without a permanent negative cache. A replay of the old UUID still returns its original job.
5. Given a publisher page or HTML response, when there is no verified direct PDF, then no document is ingested and the UI does not assert that a paywall was observed.
6. Given duplicate POSTs/deliveries, expired leases, or a worker restart, when jobs recover, then requests/documents/ingest jobs remain deduplicated and stale workers cannot attach or overwrite outcomes.
7. Given a concurrent manual upload or existing readable document, when retrieval finishes, then the user's current attachment and historical citations are preserved.
8. Given unsafe URLs, redirect destinations, mixed DNS answers, excessive bytes, or a stalled response, when retrieval runs, then it stops within the defined bounds without reaching internal services or storing invalid content.
9. Given library/chat/model features from the base branch, when the full regression suite runs, then existing workflows and automatic local-model readiness remain covered without a paid fallback or new model downloads.

## Verification boundaries

All behavior changes use TDD-first: write a Given/When/Then test, run it and record an assertion failure for the missing behavior, implement minimally, run green, refactor, and rerun relevant regressions. Import/collection errors, unavailable services, and changed test fixtures are not evidence of the intended red phase. Keep actual commands and concise output in the development journal. A green targeted test alone does not establish a green project suite.

Use deterministic provider/download fixtures, actual isolated PostgreSQL/Redis/MinIO, and the real child parser. Test denial-then-success with a fixture; it proves retry mechanics, not actual university subscription access. A separate optional user-network smoke check can establish the latter when the network/subscription is available. Do not call hosted generation or download model weights during routine checks. Fixture summary/chat verify routing and document grounding invariants; any real provider/model claim requires separately recorded output.

## Primary documentation

- [OpenAlex locations](https://help.openalex.org/data/locations/) and [open access fields](https://help.openalex.org/data/works/open-access/): per-copy URLs, OA flags, licenses, and versions.
- [OpenAlex exact filters](https://help.openalex.org/api/filtering/): DOI-based candidate lookup.
- [Semantic Scholar Graph API](https://api.semanticscholar.org/api-docs/): OA PDF and identifier fields.
- [Semantic Scholar FAQ](https://webflow.semanticscholar.org/faq): website institutional sign-in and GetFTR/LibKey access; do not infer that our API key carries those sessions.
- [Springer institutional access](https://support.springernature.com/en/support/solutions/articles/6000210868-access-institutional-online-subscriptions): institution subscription and registered IP access.
- [OrbStack networking](https://docs.orbstack.dev/docker/network): documented host VPN/DNS integration, not a live university-access check.
- [HTTPX SNI extension](https://www.python-httpx.org/advanced/extensions/#sni_hostname): explicit-IP connections retaining hostname verification.
- [MDN CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS): browser credential and cross-origin constraints.
