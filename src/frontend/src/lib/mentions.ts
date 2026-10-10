import type { components } from '@/api/generated'
import type { PillPaper } from '@/components/paper/PaperPill'

/**
 * A paper a question mentions with a composer pill (ARA-096). `start` and `end` count Unicode code points of the
 * question, as the server indexes it, so text before a pill may hold emoji or other astral characters.
 */
export type MentionSpan = components['schemas']['PaperMention']
/** A pill in a draft; `paper` holds the details for its citation card and is never sent. */
export type DraftMention = MentionSpan & { paper?: PillPaper }
/** A question being written: its text, with each pill as its label, and the pills. */
export type Draft = { text: string; mentions: DraftMention[] }

export const emptyDraft: Draft = { text: '', mentions: [] }

/** Code points, not UTF-16 units. */
export const codePoints = (text: string) => Array.from(text)

/** A sent question as text and pills for history; spans that do not match their text are left as text. */
export function mentionSegments(text: string, mentions: readonly MentionSpan[]): ({ text: string } | { mention: MentionSpan })[] {
  const chars = codePoints(text)
  const segments: ({ text: string } | { mention: MentionSpan })[] = []
  let at = 0
  for (const mention of mentions) {
    if (mention.start < at || chars.slice(mention.start, mention.end).join('') !== mention.label) return [{ text }]
    if (mention.start > at) segments.push({ text: chars.slice(at, mention.start).join('') })
    segments.push({ mention })
    at = mention.end
  }
  if (at < chars.length) segments.push({ text: chars.slice(at).join('') })
  return segments
}

/** Mentioned papers in order of first mention. */
export function mentionedPapers(mentions: readonly MentionSpan[]) {
  return [...new Set(mentions.map((mention) => mention.paper_id))]
}

/** The draft without the pills of one paper; each goes with its label and the space typed after it. */
export function withoutPaper(draft: Draft, paperId: string): Draft {
  const chars = codePoints(draft.text)
  const kept: DraftMention[] = []
  let removed = 0
  for (const mention of draft.mentions) {
    if (mention.paper_id !== paperId) {
      kept.push({ ...mention, start: mention.start - removed, end: mention.end - removed })
      continue
    }
    const end = chars[mention.end] === ' ' ? mention.end + 1 : mention.end
    chars.splice(mention.start - removed, end - mention.start)
    removed += end - mention.start
  }
  return { text: chars.join(''), mentions: kept }
}

/** The draft as it is sent: trimmed, with its spans moved by the code points trimmed from the start. */
export function trimDraft(draft: Draft): Draft {
  const text = draft.text.trim()
  const lead = codePoints(draft.text.slice(0, draft.text.length - draft.text.trimStart().length)).length
  return { text, mentions: draft.mentions.map((mention) => ({ ...mention, start: mention.start - lead, end: mention.end - lead })) }
}
