# AI Research Assistant

User-approved brief: a single-user academic research workspace for CS59300 homework. Researchers search papers, save them, upload PDFs, read grounded summaries and ask document-specific questions. Success is five working end-to-end workflows with retained source/page provenance, reproducible Docker setup and authentic development reflection.

Web SPA for desktop and mobile. Frequent tasks are searching, selecting, reading and comparing a response to its source. The first viewport is a working chat-centred composer (search, or ask a library paper), not marketing. Missing metadata/fulltext, processing, provider failure and interrupted generation are essential states.

Name: the product's wordmark is "ara.", short for AI Research Assistant. The long name stays in documentation; the interface shows only the wordmark.

Brand commitment (user-pinned 2026-10-08, UI overhaul ARA-033): the category standard played straight. A unified, chat-centred shadcn workspace that sits alongside ChatGPT, Claude, Elicit, Scite, SciSpace and Undermind and matches their craft. shadcn default neutral black/white tokens in light and dark (system preference, user toggle); Geist Sans/Mono self-hosted; collapsible sidebar with papers and recent chats/searches; one composer that searches or asks a selected paper with a compact model switcher; paper workspace pairs an in-app PDF reader with the conversation, and citations jump to and highlight evidence in the PDF. The reader owns the PDF without tabs, including replacing or removing it from its menu; the paper's details open from a circled-i button in a sheet (user feedback, ARA-097). Mobile uses an offcanvas sidebar and Chat/PDF segments. No invented claims or synthetic data in normal operation. Interface copy explains user actions and recovery, not internal engineering.

Scope: React/Vite/strictTS/Tailwind4/shadcn, Query+ReactRouter, RHF/Zod. No auth, payments, GPU prerequisite or landing page. Document requirements in docs/implementation-plan.md. Development deadline October10; five working flows and reflection remain the priority, and the user has funded the UI overhaul without deadline-driven cuts.
