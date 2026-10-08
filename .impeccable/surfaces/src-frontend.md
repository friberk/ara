---
version: 1
slug: "src-frontend"
primary_target: "src/frontend"
related_targets: []
---

# Surface brief: research workspace (whole frontend)

Scope: every route of src/frontend: home composer, search thread, library, paper workspace (reader + conversation), activity, settings. Visitor mode: Operate for shell/search/library/activity/settings; Read for answers, summaries and the PDF.

Audience and job: a single researcher at a laptop (sometimes a phone) finding papers, saving them, uploading PDFs and checking AI answers against the source. Success: the five homework workflows are obvious within seconds and every claim can be traced to its page.

Constraints: no invented claims or synthetic data; errors inline (role=alert), toasts only for success; generated content never renders raw HTML; citations must belong to the selected document; chat request UUIDs are never replayed for new paid generation.

Memorable moment: a citation chip in an answer jumps the PDF to the page and lights up the passage.

Unresolved: none at brief time.

## Direction contract

THESIS: The category standard played straight (user-pinned canon): one chat-centred shadcn workspace where searching, reading and asking happen in one composer and one thread. It refuses the docs-page arrangement of headings, form cards and tabs that hid the conversation.

OWN-WORLD: shadcn neutral oklch tokens, pure white or near-black grounds, black/white primary buttons, hairline borders, sidebar on a faint neutral ground, rounded-3xl floating composer, Geist Sans throughout, borderless list rows with muted hover, quiet status tints only on document badges, a marker-yellow evidence highlight as the only expressive colour.

STORY: The visitor lands on "What are you researching?", types a topic, scans paper rows with saved state, saves or asks one, opens it beside its PDF, reads the summary, asks a question, and clicks a page chip to see the exact evidence highlighted.

FIRST VIEWPORT: Left, the collapsible sidebar (New research, Search, Library, Activity, Papers, Recent, settings and theme in the footer). Centre, a 28px greeting above a max-w-3xl composer with provider and attach controls and a round send button, followed by suggestion chips. Primary action: the composer's send button.

FORM: canon (user-pinned standing exit, comparison set ChatGPT, Claude, Elicit, Undermind); position 1; seed key: none, because the user pinned the direction, so no roll ran. Signature interaction: evidence jump with text-layer highlight. Motion grammar: streaming caret, message enter, sidebar collapse, panel resize, highlight pulse; nothing else moves.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
