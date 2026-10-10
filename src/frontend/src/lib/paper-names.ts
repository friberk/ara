import type { IncludedPaper, Paper } from '@/api/types'

/** Paper chips shown before the rest collapse into "+N more"; a chat may include any number of papers (ARA-088). */
export const VISIBLE_PAPER_CHIPS = 3

type Named = Pick<IncludedPaper, 'title' | 'first_author' | 'year'>

/** The family name of "Ada Researcher" or "Researcher, Ada". */
function surname(name: string) {
  const trimmed = name.trim()
  if (trimmed.includes(',')) return trimmed.split(',')[0]!.trim()
  return trimmed.split(/\s+/).at(-1) ?? trimmed
}

/** A citation-style name such as "Vaswani 2017"; the title when the paper has no authors. */
export function shortPaperName(paper: Named) {
  const author = paper.first_author ? surname(paper.first_author) : ''
  if (author) return paper.year ? `${author} ${paper.year}` : author
  const title = paper.title?.trim() || 'Untitled paper'
  return title.length > 40 ? `${title.slice(0, 39).trimEnd()}…` : title
}

/**
 * APA 7's in-text author-date part, which names a paper in a chat citation (ARA-110): "Han, 2018", "Han & Shin, 2018",
 * "Han et al., 2018", "Han, n.d."; without authors a short title stands in.
 */
export function apaAuthorDate(paper: Pick<Paper, 'title' | 'authors' | 'year'>) {
  const authors = authorShort(paper.authors)
  if (authors) return `${authors}, ${paper.year ?? 'n.d.'}`
  const title = shortPaperName({ title: paper.title, first_author: null, year: null })
  return paper.year ? `${title}, ${paper.year}` : title
}

export function namedPaper(paper: Pick<Paper, 'title' | 'authors' | 'year'>): Named {
  return { title: paper.title, first_author: paper.authors[0] ?? null, year: paper.year }
}

/** "Attention Is All You Need", or "Attention Is All You Need +2" for a chat over three papers. */
export function chatPapersLabel(papers: Pick<IncludedPaper, 'title'>[]) {
  const first = papers[0]
  if (!first) return null
  const title = first.title?.trim() || 'Untitled paper'
  return papers.length > 1 ? `${title} +${papers.length - 1}` : title
}

/**
 * The label of a paper's mention pill: "Karpukhin 2020" as its chips name it, else its full title. The question
 * carries the label as text, and the pill's paper id with it (ARA-096).
 */
export function mentionName(paper: Pick<Paper, 'title' | 'authors' | 'year'>) {
  const author = paper.authors[0] ? surname(paper.authors[0]) : ''
  return author && paper.year ? `${author} ${paper.year}` : paper.title?.trim() || 'Untitled paper'
}

/** The author part of a citation: "Vaswani", "Vaswani & Shazeer" or "Vaswani et al."; empty without authors. */
export function authorShort(authors: readonly string[]) {
  const names = authors.map((name) => name.trim()).filter(Boolean).map(surname)
  if (names.length > 2) return `${names[0]} et al.`
  return names.join(' & ')
}

export type CitationParts = { authors: string; year: string; venue: string }

/**
 * The parts of a paper's short citation, each empty when the paper lacks it: "Vaswani et al.", "2017" and "NeurIPS".
 * PaperCitation sets them in APA/Harvard order for the picker and the summary dialog.
 */
export function citationLine(paper: Pick<Paper, 'authors' | 'year'> & { venue?: string | null }): CitationParts {
  return { authors: authorShort(paper.authors), year: paper.year ? String(paper.year) : '', venue: paper.venue?.trim() ?? '' }
}

/** The longest pill label; the server accepts 500 characters and the question carries the label as text. */
const LABEL_CHARS = 300

/**
 * A mention pill's label, which the question also carries as text (ARA-096): the paper's title, cut only when very
 * long, or "Karpukhin 2020" when it has none.
 */
export function mentionLabel(paper: Pick<Paper, 'title' | 'authors' | 'year'>) {
  const title = paper.title?.trim()
  if (!title) return mentionName(paper)
  return title.length > LABEL_CHARS ? `${title.slice(0, LABEL_CHARS - 1).trimEnd()}…` : title
}

/** PaperCitation as plain text, which describes a mention pill to screen readers: "Han et al. (2018), Venue". */
export function shortCitation(paper: Pick<Paper, 'authors' | 'year'> & { venue?: string | null }) {
  const { authors, year, venue } = citationLine(paper)
  const lead = authors && year ? `${authors} (${year})` : authors || year
  return [lead, venue].filter(Boolean).join(', ')
}
