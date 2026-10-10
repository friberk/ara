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
 * How @ mentions a paper in a question: "Karpukhin 2020" as its chips name it, else its full title. The server keeps
 * a paper the question names this way (ARA-088).
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

/**
 * A paper's short citation from what it has, such as "Vaswani et al. · 2017 · NeurIPS", for the picker and the
 * summary dialog. Missing parts are skipped; a paper with none of them has an empty line.
 */
export function citationLine(paper: Pick<Paper, 'authors' | 'year'> & { venue?: string | null }) {
  return [authorShort(paper.authors), paper.year ? String(paper.year) : '', paper.venue?.trim() ?? ''].filter(Boolean).join(' · ')
}
