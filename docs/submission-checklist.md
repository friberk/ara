# Submission preparation

Assignment deadline: October10,11:59PM; plan targets10PM. Application60%, reflection40%.

## Repository

- Repository: <https://github.com/friberk/ara> (private, all branches; invite the course staff so the submitted link opens). Demo: <https://vps-eb56b28c.vps.ovh.us>, open on campus, demo username and password elsewhere (ARA-107); share the login with the course staff.
- Exclude .env, original uploads, generated test data and private screenshots. Existing assignment files/writing skills are user references, not application dependencies.
- Rehearse README startup in a clean isolated Compose project. Verify all five workflows and restart persistence.

## Demonstration video

An actual continuous browser walkthrough is retained at ignored `docs/evidence/generated/live-demo/live-demo.webm`, with screenshots and a result record alongside it. It uses live OpenAlex, the public arXiv *Attention Is All You Need* PDF and configured OpenAI Luna/low. Watch it before submission and add narration or rerecord if desired. It shows:

1. Search a topic with OpenAlex or Semantic Scholar; show source selector and bibliographic data.
2. Save a result, open Library and refresh to show persistence.
3. Attach or upload a PDF; show processing and extracted fields.
4. Generate a summary grounded in actual PDF content; inspect a supporting page.
5. Start a conversation, ask a dataset question, inspect a citation and refresh history.

The recording predates two final display corrections: per-answer model/effort labels and complete source excerpts. Later verified screenshots show those corrections; no additional paid call was needed.

Deterministic fixture runs are rehearsals and automated verification, not live-provider demonstrations. Keep video/screenshots free of credentials. Browser test traces and UI captures are available under ignored artifact directories.

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
