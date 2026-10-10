# Submission preparation

Assignment deadline: October10,11:59PM; plan targets10PM. Application60%, reflection40%.

## Repository

- Repository: <https://github.com/friberk/ara> (private, all branches; invite the course staff so the submitted link opens). Demo: <https://vps-eb56b28c.vps.ovh.us>, open on campus, demo username and password elsewhere (ARA-107); share the login with the course staff.
- Exclude .env, original uploads, generated test data and private screenshots. Existing assignment files/writing skills are user references, not application dependencies.
- Rehearse README startup in a clean isolated Compose project. Verify all five workflows and restart persistence.

## Demonstration video

The submitted video is `docs/evidence/generated/demo/final/ara-demo.mp4` (ARA-113). Like all generated evidence it is ignored by Git and is not uploaded anywhere else; it goes to Brightspace only.

- **Format:** 4:40, 1920x1080, H.264, silent. Each clip is also kept on its own in `final/clips/`.
- **How it was made:** recorded with testreel on an empty, isolated `ara-demo` stack (no papers, chats or search history), using live OpenAlex and OpenAI Luna/low. Black title cards in the ara. brand separate the clips. The scripts are in [scripts/demo](../scripts/demo/README.md), and `node record.mjs --reset --run <name>`, then `node assemble.mjs --run <name>`, records a new take.
- **Papers:** three ReDoS papers.
  - *The impact of ReDoS in practice* (ESEC/FSE 2018). OpenAlex stores its PDF.
  - The SoK, arXiv 2406.11618. OpenAlex has no copy, so the arXiv PDF is uploaded.
  - *Regular Expression Denial of Service Induced by Backreferences*, the USENIX Security '26 PDF.

It covers hw1's five required items, plus the main extras:

1. Search: OpenAlex results with authors, year, abstract and links (required 1).
2. Save: the FSE paper joins the library and its PDF arrives automatically (required 2).
3. No stored copy: the SoK is saved and its arXiv PDF is uploaded (required 3).
4. Upload: the USENIX PDF's title, authors, year and abstract are extracted (required 3).
5. Summary: a summary is generated and a page citation highlights its passage (required 4).
6. Question: "What are the major limitations?" with cited pages, the model menu and the context meter (required 5).
7. Across papers: one question over two papers mentioned with @.
8. Library after a full restart: filter, reload, edit details, reopen a chat with ⌘K.
9. Settings.

Watch it once before submitting. Things a viewer may notice:

- Long waits are sped up, and a "Sped up N×" badge shows while they are.
- Clip 5 uses "Regenerate summary", because summaries start by themselves when a PDF is ready.
- The USENIX paper's details are completed from OpenAlex's arXiv record after extraction, so its sources dialog credits OpenAlex; the clip's card says so.

The older walkthrough at ignored `docs/evidence/generated/live-demo/live-demo.webm` is superseded. Deterministic fixture runs are rehearsals and automated verification, not live-provider demonstrations. Keep video/screenshots free of credentials. Browser test traces and UI captures are available under ignored artifact directories.

## Authentic reflection

Use docs/agent-development-log.md, docs/verification-phase0.md, docs/application-review.md and final verification evidence. Discuss the actual agent used, useful contributions, how much inspection/debugging was needed and lessons about steering agents. Add your own experience and judgment; do not present this checklist as your personal report.

Useful real examples to capture from the conversation:

- Context7 installed/enabled metadata vs failed connection call and corrected wording.
- Concurrent npm upgrade invalidating an initial test, followed by serialized rerun.
- Independent reviewer identifying wrong metadata import, poisoned PDF upload and document/job state divergence; owner red/green regressions.
- ASGI cancellation reproducing lost partial persistence, followed by AnyIO shielded cleanup.
-390px mobile viewport with409px overflow and the measured CSS correction.

Screenshots should show relevant prompt, visible output, proposed code and corrective instruction. Hidden model reasoning is unavailable and must not be claimed. Agent successes and failures in the journal are factual evidence, not a fabricated narrative.

## Brightspace

Submit the repository link, short video and student-written reflection, then verify the upload/link. No Brightspace submission has been made by this coding session.
