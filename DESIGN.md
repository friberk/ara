---
name: AI Research Assistant
description: A chat-centred research workspace in stock shadcn neutral, where every answer can be checked against its page.
colors:
  ink: "oklch(0.205 0 0)"
  ink-foreground: "oklch(0.985 0 0)"
  paper: "oklch(1 0 0)"
  foreground: "oklch(0.145 0 0)"
  quiet-surface: "oklch(0.97 0 0)"
  muted-foreground: "oklch(0.556 0 0)"
  hairline: "oklch(0.922 0 0)"
  ring: "oklch(0.708 0 0)"
  sidebar-ground: "oklch(0.985 0 0)"
  ink-dark: "oklch(0.922 0 0)"
  paper-dark: "oklch(0.145 0 0)"
  card-dark: "oklch(0.205 0 0)"
  quiet-surface-dark: "oklch(0.269 0 0)"
  muted-foreground-dark: "oklch(0.708 0 0)"
  hairline-dark: "oklch(1 0 0 / 10%)"
  input-dark: "oklch(1 0 0 / 15%)"
  destructive: "oklch(0.577 0.245 27.325)"
  destructive-dark: "oklch(0.704 0.191 22.216)"
  evidence-marker: "oklch(0.93 0.13 96 / 0.75)"
  success: "oklch(0.45 0.11 155)"
  success-muted: "oklch(0.96 0.03 155)"
  success-dark: "oklch(0.8 0.12 155)"
  success-muted-dark: "oklch(0.3 0.05 155)"
  warning: "oklch(0.5 0.11 70)"
  warning-muted: "oklch(0.96 0.04 85)"
  warning-dark: "oklch(0.82 0.12 80)"
  warning-muted-dark: "oklch(0.32 0.05 75)"
typography:
  display:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.025em"
    fontFeature: "\"ss01\", \"cv11\""
  headline:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.375
    letterSpacing: "-0.025em"
  reading:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 400
    lineHeight: "28px"
  composer:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: "24px"
  body:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "24px"
  label:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1
  identifier:
    fontFamily: "Geist Mono Variable, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "14px"
  2xl: "18px"
  3xl: "22px"
  4xl: "26px"
  full: "9999px"
spacing:
  hairline-gap: "4px"
  control-gap: "6px"
  gutter: "16px"
  row: "24px"
  stack: "28px"
  header: "48px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ink-foreground}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-outline:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-outline-hover:
    backgroundColor: "{colors.quiet-surface}"
  button-ghost:
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-ghost-hover:
    backgroundColor: "{colors.quiet-surface}"
  button-send:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ink-foreground}"
    rounded: "{rounded.full}"
    size: "28px"
  composer:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.foreground}"
    typography: "{typography.composer}"
    rounded: "{rounded.3xl}"
    padding: "14px 16px 8px"
  input:
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "4px 10px"
    height: "32px"
  user-message:
    backgroundColor: "{colors.quiet-surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.reading}"
    rounded: "{rounded.2xl}"
    padding: "10px 16px"
  summary-card:
    backgroundColor: "{colors.quiet-surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.reading}"
    rounded: "{rounded.2xl}"
    padding: "14px 20px"
  citation-chip:
    backgroundColor: "{colors.quiet-surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 6px"
    height: "20px"
  status-badge-ready:
    backgroundColor: "{colors.success-muted}"
    textColor: "{colors.success}"
    rounded: "{rounded.4xl}"
    padding: "2px 8px"
    height: "20px"
  status-badge-processing:
    backgroundColor: "{colors.warning-muted}"
    textColor: "{colors.warning}"
    rounded: "{rounded.4xl}"
    padding: "2px 8px"
    height: "20px"
  sidebar-item:
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "8px"
    height: "32px"
  sidebar-item-active:
    backgroundColor: "{colors.quiet-surface}"
---

# Design System: AI Research Assistant

## Overview

**Creative North Star: "The Category Standard, Played Straight"**

The workspace sits in the same class as ChatGPT, Claude, Elicit and Undermind and does not try to out-design them. Stock shadcn neutral tokens, Geist throughout, a collapsible sidebar, and one floating composer that either searches the literature or asks a selected paper. The craft goes into clarity and provenance rather than ornament: every answer carries page chips, and every chip leads back to the sentence on the page.

The grounds are pure white in light mode and near-black in dark, following the system preference with a user toggle in the sidebar footer. Colour is withheld almost completely. The interface is achromatic ink on paper. A marker-yellow highlight in the PDF is the one expressive colour, and quiet green and amber tints mark status. Density is moderate: reading text is set larger than the controls around it (15.5px on a 28px line), and lists are borderless rows separated by hairlines rather than stacks of cards.

The rejection is explicit and comes from the direction contract. Do not use the docs-page arrangement of headings, form cards and tabs that hid the conversation. The thread and the composer are the page.

**Key Characteristics:**
- Zero-chroma oklch neutrals for every surface, text and border, in both themes.
- One floating, heavily rounded composer is the primary input on every route that takes text.
- Borderless list rows divided by hairlines; cards reserved for summaries and the upload drop zone.
- PDF pages stay white paper in both themes, so the evidence mark is identical in light and dark.
- Motion only answers a user action, and reduced motion removes it.

## Colors

An achromatic shadcn neutral system with three narrow, role-locked exceptions: evidence yellow, status tints and destructive red.

### Primary
- **Ink** (light oklch(0.205 0 0), dark oklch(0.922 0 0)): primary buttons, the round send button and the sidebar brand mark. In dark mode it inverts to near-white ink on a near-black ground. Black and white is the whole accent.

### Tertiary
- **Evidence Marker Yellow** (oklch(0.93 0.13 96 / 0.75), applied as a 55% mix over the canvas): the cited-sentence highlight in the PDF text layer and its one-shot pulse ring. Nothing else. The `--evidence` token has a single value in both themes because the pages under it are always white paper.
- **Status Green** (text oklch(0.45 0.11 155) on oklch(0.96 0.03 155); dark text oklch(0.8 0.12 155) on oklch(0.3 0.05 155)): status badges that mean done or usable, such as a completed job or an available model.
- **Status Amber** (text oklch(0.5 0.11 70) on oklch(0.96 0.04 85); dark text oklch(0.82 0.12 80) on oklch(0.32 0.05 75)): status badges that mean in progress or incomplete, such as a running job or an interrupted answer.
- **Destructive Red** (light oklch(0.577 0.245 27.325), dark oklch(0.704 0.191 22.216)): errors and destructive actions only. It appears as a 10% tint behind red text on inline alerts, failed badges, the failed-PDF icon and delete menu items, never as a solid fill.

### Neutral
- **Paper** (light oklch(1 0 0), dark oklch(0.145 0 0)): the app ground, the composer in light mode, and outline buttons.
- **Card** (dark oklch(0.205 0 0)): popovers, plus the composer and floating controls in dark mode, where a lighter fill replaces the shadow.
- **Foreground** (light oklch(0.145 0 0), dark oklch(0.985 0 0)): all primary text. Abstracts sit at 80% opacity of it.
- **Quiet Surface** (light oklch(0.97 0 0), dark oklch(0.269 0 0)): secondary, muted and accent are one value. It covers hover rows, ghost-button hover, user message bubbles, the summary card (at 60%), citation chips and code.
- **Muted Ink** (light oklch(0.556 0 0), dark oklch(0.708 0 0)): bylines, counts, footnotes, placeholder text and inactive icons.
- **Hairline** (light oklch(0.922 0 0), dark oklch(1 0 0 / 10%)): every border and row divider. Dark inputs use oklch(1 0 0 / 15%).
- **Sidebar Ground** (light oklch(0.985 0 0), dark oklch(0.205 0 0)): the faint neutral panel behind navigation.
- **Ring** (light oklch(0.708 0 0), dark oklch(0.556 0 0)): focus outlines (2px, offset 2px) and the active resize handle.

### Named Rules
**The Black-and-White Rule.** Every surface, text colour and border has zero chroma. If a new screen needs emphasis, it gets weight, size or ink, not a hue.

**The One Highlighter Rule.** Evidence yellow appears only on cited text in the PDF. It is never used for UI emphasis, selection, chips or badges.

**The Status Tint Rule.** Green and amber appear only inside status badges, as a muted ground with matching text. They never colour buttons, links, icons outside a badge, or row backgrounds.

**The Red Means Error Rule.** Destructive red is reserved for failures and destructive actions, always as a tint behind red text.

## Typography

**Display Font:** Geist Variable (with ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif)
**Body Font:** Geist Variable, the same family throughout
**Label/Mono Font:** Geist Mono Variable (with ui-monospace, SFMono-Regular, Menlo, monospace)

**Character:** One neutral grotesque carries everything. The face is self-hosted through @fontsource, with stylistic set ss01 and cv11 enabled on body. Hierarchy comes from size and a single step from regular to semibold, and headings tighten their tracking slightly.

### Hierarchy
- **Display** (600, 28px, tight tracking, balanced wrap): the home greeting above the composer ("What are you researching?"). Used once per screen at most.
- **Headline** (600, 1.5rem, tight tracking): the page title on Search, Library and Settings.
- **Title** (600, 17px, line-height 1.375, tight tracking): paper titles in search rows. Library rows use the same weight at 1rem, and the paper header above the PDF at 1.125rem.
- **Reading** (400, 15.5px, 28px line): assistant answers, user messages and summaries. This is the conversation's reading voice, one step above the interface.
- **Composer** (400, 15px, 24px line): text typed into the composer.
- **Body** (400, 0.875rem, 24px line): abstracts (clamped to three lines with Show more), descriptions, links and menus. Long prose is capped near 70ch.
- **Label** (500, 0.75rem): badges, citation chips, the composer footnote and metadata captions. Labels use sentence case and never uppercase tracking.
- **Identifier** (Geist Mono, 400, 0.75 to 0.8125rem): DOIs, unrecognised model ids and code. Mono marks things a user might copy exactly.

### Named Rules
**The Mono Is for Identifiers Rule.** Geist Mono is used only for DOIs, raw model ids, DOI input fields and code. It is never used for decoration, labels or numerals. Counts and page numbers use tabular figures in Geist Sans instead.

**The Sentence Case Rule.** All interface copy (buttons, headings, badges, menu items, toasts) is in sentence case. There are no uppercase eyebrows or tracked-out labels.

## Brand

The product's mark is the wordmark "ara." (the dot is part of the name), set in Instrument Serif Italic.
- **The Only Serif Rule.** The wordmark is the only serif in the system. It is an SVG outline (`branding/ara-wordmark.svg`, inlined by `AraWordmark`), not a UI font: no webfont is loaded and it never appears as text styling.
- **Monochrome.** It uses `fill="currentColor"` and follows the foreground token in light and dark. Never recolour it.
- **Sizes.** Minimum height is 16px. Keep clear space of at least the width of the dot on every side. The sidebar header uses 26px; collapsed to icons it shows the "a." mark (`AraMark`).
- **Never** stretch it, recolour it or retype it in Geist. The favicon (`branding/favicon.svg`) is the "a." on an ink tile and inverts under a dark browser theme. Regeneration steps are in `branding/README.md`.

## Layout

The shell is the shadcn sidebar layout. On desktop a 16rem sidebar collapses to a 3rem icon rail (⌘B). Below 768px it becomes an 18rem offcanvas sheet. The sidebar holds New research, Find papers and chats (⌘K command palette), and Library, then Papers and Recent groups, with Settings and Theme in the footer. The main column has a 48px header that pages can fill with a title, a status badge or a chat switcher: the open chat's title (its menu holds Rename and Delete), a History icon that opens a popover of this paper's chats newest first with compact relative times ("now", "12m", "3h", "2d", then "Oct 2"), and the New conversation icon.

Content routes centre a single column at max-w-3xl (48rem). Home centres the display greeting, the composer and suggestion chips vertically, with a 28px gap and 12vh of extra bottom padding so the group sits slightly above centre. Search pins the composer to the bottom of the results column, like a chat thread. Search results and library entries are borderless rows with 24px and 20px vertical padding, divided by hairlines.

The paper workspace is a resizable two-panel split separated by a grip handle. The reader takes 50% by default, at least 30%, and can collapse fully. The conversation keeps at least 35%. The reader has no tabs: the paper header (its bibliography) leads, then the PDF, or, until the paper has one, the ways to get it (retrieval progress, the DOI link, upload, preparation steps, failure with retry). The PDF's own bar carries its controls: paging and zoom, then the PDF menu. The top bar keeps the paper's title, because the reader can be hidden. Below 768px the split becomes two segments, Chat and PDF. The whole reader column is the app background, the same white (near-black in dark mode) as the conversation. PDF pages are centred in a 16px gutter with 16px between pages, and the paper header and the PDF bar line up with the page column: as wide as a page at the current zoom, never wider than the reader less its gutters, so all three share one left edge.

## Elevation & Depth

The system is flat by default and uses tonal layering. Depth comes from the sidebar's faint ground, the quiet-surface fill of hovered rows, bubbles and summaries, and hairline borders. Shadows are rare and soft, and in dark mode they disappear: floating surfaces move to the lighter card tone instead.

### Shadow Vocabulary
- **Composer float** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.04), 0 4px 16px -4px rgb(0 0 0 / 0.08)`): the composer at rest in light mode.
- **Composer focus** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.05), 0 8px 24px -6px rgb(0 0 0 / 0.12)`): the composer while its text field has focus. The border also moves to the ring at 60%.
- **Floating control** (`box-shadow: 0 2px 8px -2px rgb(0 0 0 / 0.15)`): the round "Scroll to latest message" button over the thread.

### Named Rules
**The Soft Lift Rule.** Only surfaces that float over scrolling content (the composer and floating controls) get a shadow. PDF pages lie on the reader's white ground with a 1px border-colour ring (`ring-1 ring-border`, radius 2px) as their only edge, in both themes. Shadows are soft, low-opacity and blurred. Hard offset shadows are not part of this world.

**The Dark Mode Lifts by Tone Rule.** In dark mode, floating surfaces drop their shadow and use the card tone (oklch(0.205 0 0)) instead.

## Shapes

Corners follow the shadcn scale derived from a 10px base radius. Controls (buttons, inputs, tabs) use 10px, small buttons and icon buttons are capped at 8 to 12px, and menu items and sidebar rows use 8px. Radius grows with the size of the surface: grouped settings use 14px, user bubbles and the summary card 18px, and the composer 22px. Fully round shapes are reserved for the send and stop buttons, the scroll-to-latest button, suggestion chips and badges. Citation chips are small 6px rectangles so they sit inside running text. PDF pages keep a near-square 2px corner because they represent paper.

## Components

### Buttons
Quiet, compact and monochrome.
- **Shape:** gently rounded (10px), 32px tall by default and 28px for row actions (`sm`), with 16px icons (14px at `sm`).
- **Primary:** ink fill with paper text. It is used sparingly, mostly for the round send button and the confirming action in dialogs.
- **Outline:** a paper ground with a hairline border, turning quiet-surface on hover. It is the standard row action, for example Save to library, Open paper and Try again.
- **Ghost:** no ground until hover. Used for secondary row actions (Ask about this paper), toolbar icons and composer controls.
- **Hover / Focus:** hover changes only the background colour. Focus shows a 3px ring at 50% ring colour, and an active press shifts the button down 1px.
- **Destructive:** a red tint behind red text, used only in confirm dialogs and menu items that delete.

### Chips
- **Citation chip:** a 20px-tall quiet-surface tab with a 6px corner, label weight, tabular figures and "p. N" text. Hovering darkens it by mixing in 10% foreground. On pointer devices it previews the cited passage in a hover card. Activating it runs the evidence jump.
- **Suggestion chips:** fully round outline buttons with regular-weight muted text below the home composer. They show recent searches first and fill the rest with example topics.
- **Paper context chip:** sits in the composer header when a paper is selected, and removing it returns the composer to search.

### Cards / Containers
- **Corner Style:** 18px for the summary card, 14px for the upload drop zone and grouped settings.
- **Background:** the summary card uses quiet surface at 60% with no border. The upload zone uses card with a hairline, and its inner drop target uses a dashed hairline.
- **Shadow Strategy:** none. See Elevation & Depth.
- **Internal Padding:** 14px by 16 to 20px for the summary, 16px for the upload zone.
- Search results and library entries are not cards. They are rows divided by hairlines.

### Inputs / Fields
- **Style:** a 32px field with a hairline input border, 10px radius and transparent ground (input tone at 30% in dark mode).
- **Focus:** the border shifts to the ring colour, with a 3px ring at 50%.
- **Error / Disabled:** aria-invalid turns the border red and adds a red ring tint. Disabled fields drop to 50% opacity.

### Navigation
- **Sidebar:** 32px rows with an 8px corner on the sidebar ground. Hover and active states share the sidebar accent (quiet surface), and the active row adds medium weight. Group labels use muted text in sentence case. Recent items have overflow menus for rename, delete and remove.
- **Mobile:** the sidebar opens as an offcanvas sheet from the header trigger. The paper workspace switches between Chat and PDF segments.
- **Tabs:** a segmented control on a muted track. The active segment is raised with a small shadow, and inactive labels sit at 60% foreground.

### Paper header
The reader opens with the paper's bibliography, laid out as a reading header with no surface or hairline of its own, on the reader's one background: the title at 1.125rem semibold, every author, then the year and the italic venue as running text, the DOI and catalog record links, and, under a small "Abstract" heading (label size, medium weight), the abstract clamped to three lines with Show more. A field the paper lacks is left out; a missing abstract keeps its heading and says so in muted text. The PDF bar follows: a "PDF" heading in the same label style with the file name after it in muted text (no separator glyph), and the PDF's controls at the right. The file name truncates first and gives way entirely in a bar narrower than 24rem; the PDF menu still names it. An earlier PDF version's bar names that version's file, under its banner. Above a PDF the header and the bar are the first things in the viewer's scroll column: the header scrolls away with page 1, and the bar docks at the top of the reader on the app background, showing its bottom hairline only once docked (the border is always there and only takes colour, so docking never shifts the pages). Paging lands a page's top 8px under the docked bar, and a citation is centred in the space below it. With no ready PDF the bar is the heading alone, nothing to page or zoom, and leads the ways to get one, whose own headings sit under "PDF". In a reader tab for another paper it describes that paper. Edit details (a ghost button whose label becomes screen-reader text in a reader narrower than 28rem) and the circled-i sit at the title's top right.

### Sources and search index
The circled-i (Lucide Info, a ghost icon button named "Sources and search index") opens a stock centred Dialog that holds only what lies behind the bibliography: where each field came from with Look up again, the identifiers in Geist Mono with copy buttons, the search index as one plain sentence ("Searching 64 passages in 32 sections with …", no status pill; only building, with a spinner line and progress, and failure say more), and, for the workspace's own paper, a destructive Delete paper after a hairline. Esc and the close button return focus to the circled-i; on a phone the dialog fits the screen and scrolls inside.

### PDF menu
The PDF bar ends with a vertical-ellipsis button named "PDF options". Its dropdown starts with a non-interactive label: the file name, then pages and size in tabular figures, then the source ("Uploaded" or "Downloaded from OpenAlex"), in muted label text. Open original and Download follow. For the paper's current PDF the menu adds Replace PDF, which opens the upload in a dialog, and Remove PDF, a destructive item. Remove PDF opens an alert dialog that states what happens, from the server's preview, with Cancel focused: the reader returns to upload, existing conversations keep using the PDF and new questions need a new PDF, and only what no conversation uses is deleted. Earlier versions and other papers' PDFs only open or download. A chat on an earlier PDF reads it in a reader tab under a "Showing an earlier PDF version" banner, whose button returns to the current PDF or, when the paper has none, offers to add one.

### PDF state icon
`PdfStateIcon` is the leading icon of every paper row (Library, sidebar Papers, command palette, @ picker) and appears in the paper workspace header only when the PDF is not ready. It is 16px and uses ink, muted and destructive only, never green or amber: attached is `FileText` in foreground ink, none is `FileQuestion` in muted ink, preparing is a muted `LoaderCircle` that spins only when motion is allowed, and failed is a destructive `FileWarning`. A tooltip opens on hover and keyboard focus ("PDF attached", "No PDF yet", "Preparing PDF…", "PDF couldn’t be read") and the same text names the icon for screen readers. Inside a link or option the icon is not a tab stop. There is no text badge for PDF state.

### Status Badges
Fully round, 20px tall, label size at regular weight, with a leading 12px icon. Completed and available states use the green tints. Processing, running and interrupted use the amber tints. Failed uses the destructive tint. PDF state is not a badge; see the PDF state icon. The processing icon spins only when the user allows motion.

### Composer (signature)
The single input surface of the app. It is a 22px-radius floating form on paper (card in dark mode) with the soft composer shadow. An optional header row holds context chips. The auto-growing textarea runs from 44px (64px on home) up to 240px. Below it, a toolbar holds leading controls (attach, provider switcher) on the left, trailing controls (model and reasoning switcher) on the right, and a 28px round ink send button that becomes Stop while generating. Enter sends and Shift+Enter adds a new line. An optional centred footnote of 12px muted text sits beneath it and explains why it is disabled or reminds the user to check claims.

Reasoning choices come from the selected model's backend capabilities. Settings and the composer show **None**, **Low**, **Medium** and **High** for verified IFM models; GPT retains its own levels, including **Extra high** and **Max**. Verified per-model aliases resolve older IFM preset/enabled preferences to High without a false unsaved-change state. Binary-only models use a **Reasoning** toggle, with Enabled/Disabled state, rather than an effort menu. Incomplete capabilities explain that reasoning is model-controlled. Unavailable models preserve the preference and hide editing until readiness returns. Deliberate model switches store an explicit supported level; later preset changes do not move that choice. Historical Runtime preset/Reasoning enabled labels describe stored requests without rewriting them.

Installed local models prepare automatically when runtime or capability checks become stale. Settings shows **Preparing model**, the current phase and background continuity; preparation has no transfer percentage or Pause button. Selection remains unavailable until the server confirms readiness, then enables through polling. Temporary unavailability preserves the saved model and reasoning effort. Settings calls verification-only work **Model preparation**, including its history. Failed preparation offers **Retry preparation** with retained weights, or an explicit **Download** if weights disappeared; failed transfer/deletion actions name their respective retries. Routine upgrades require no **Verify again** action.

### Conversation thread
User turns are right-aligned quiet-surface bubbles (18px radius, at most 85% width). Assistant turns are unbubbled reading-size prose with inline citation chips, followed by a Sources row of chips and a muted meta line (copy, model name, reasoning level). An answer is a one-column grid at minmax(0, 1fr), so long links and identifiers wrap and wide tables and code scroll inside it rather than widening the thread. The paper chips above a multi-paper thread sit on an opaque row; while the thread is scrolled, a hairline divides it from the header and chips. While waiting, a muted "Preparing a response…" line pulses. A round floating button returns the user to the latest message.

### Evidence jump (signature interaction)
Selecting a citation chip scrolls the PDF to the cited page and marks the supporting sentence in the text layer to the exact character, including sentences that start or end mid-line. The mark is centred vertically in the part of the reader below the docked PDF bar, with a smooth scroll (instant under reduced motion). It is tinted with evidence yellow at a 55% mix and a 2px corner, then pulses once with a 4px yellow ring over 1.2s on `cubic-bezier(0.16, 1, 0.3, 1)`. The rest of the cited chunk stays untinted so only the evidence reads. In forced-colours mode the mark uses the system Highlight colour.

### Feedback
Errors are inline destructive alerts with role=alert, an icon, the message and an optional Try again button, placed next to the thing that failed. Toasts (sonner) confirm completed actions only, such as "Saved to library", "Conversation renamed" or "Processing queued again". Loading uses skeletons that match the final shape, plus a status role.

## Do's and Don'ts

### Do:
- **Do** take every surface, text and border colour from the zero-chroma neutral tokens, in both themes.
- **Do** keep evidence yellow (oklch(0.93 0.13 96 / 0.75)) for cited text in the PDF only, and use the same value in light and dark because the page is always white.
- **Do** keep green and amber inside status badges, as a muted ground with matching text.
- **Do** route any new text input through the composer (22px radius, soft float shadow, round send button) instead of a bordered form card.
- **Do** list papers, chats and jobs as borderless rows divided by hairlines inside a max-w-3xl column.
- **Do** set conversational and summary prose at 15.5px on a 28px line, and interface text at 14px.
- **Do** use Geist Mono only for DOIs, raw model ids and code.
- **Do** show errors inline with role=alert beside what failed, and use toasts only to confirm success.
- **Do** write all copy in sentence case, describing the user's action and how to recover, not internal engineering.
- **Do** animate only in response to a user action (send, collapse, resize, citation jump), and honour prefers-reduced-motion.

### Don't:
- **Don't** introduce a brand hue, gradient or tinted neutral. The accent is black and white.
- **Don't** use evidence yellow for UI emphasis, selection, badges or chips.
- **Don't** send errors to toasts.
- **Don't** wrap search results or library entries in individual cards, or rebuild the docs-page arrangement of headings, form cards and tabs that hid the conversation.
- **Don't** add uppercase eyebrows, tracked-out labels or kickers above headings.
- **Don't** use hard offset shadows or heavy elevation. Floating surfaces get the soft lift in light mode and the card tone in dark mode.
- **Don't** invert or tint PDF pages in dark mode, or follow the theme with the evidence mark.
- **Don't** use glyph characters as icons. Icons are Lucide SVGs, hidden from assistive technology when decorative.
- **Don't** add ambient or idle motion. Nothing moves unless the user caused it, except progress indicators.
