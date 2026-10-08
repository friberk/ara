# Research workspace visual system

Approved direction: an academic reading workspace. Operate mode for search/library/settings, Read mode for paper/source/answers. The plan fixes the visual world; no additional concept-selection gate is needed.

## Tokens

- Background #f8fafb, primary surface #ffffff, text #17242e, muted text #52616d, border #dce3e8.
- Accent #175c79 with #eaf3f7 surface; error #9f283b; success #23634b.
- System sans for UI; system serif optional for long paper headings. Body16px/1.6; small14px/1.5; h1 clamp28–38px; h2 22px.
- Spacing4/8/12/16/24/32/48px. Reading width72ch, sidebar220px, paper metadata260px. Controls radius8px; composed reading panels12px.
- Visible2px focus ring, text selection accent tint, underline offset3px. Respect reduced motion.

## Composition and states

Desktop left navigation beside a wide workspace. Search form, provider control and content list carry the opening screen. Paper details place bibliography beside summary/chat. Mobile collapses navigation without horizontal scrolling; content stacks. Empty/loading/error/status are text-based and actionable. Preserve scroll when reading earlier streaming messages. Citation buttons reveal a genuine excerpt/page. No raw HTML from sources/models.

## Verification

Desktop1440 and mobile390 captures, keyboard navigation, contrast, loading/error/empty states, browser overflow. No invented statistics or marketing copy. Review UI against these tokens and the working five workflows.
