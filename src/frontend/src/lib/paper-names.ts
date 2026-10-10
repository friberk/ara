import type { IncludedPaper, Paper } from '@/api/types'

/** A chat covers at most this many papers (ARA-088); the server refuses a sixth. */
export const MAX_CHAT_PAPERS = 5

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

/** "Karpukhin et al., 2020" under a paper's title. */
export function paperByline(paper: Pick<Paper, 'authors' | 'year'>) {
  const author = paper.authors[0] ? surname(paper.authors[0]) : null
  const who = author && paper.authors.length > 1 ? `${author} et al.` : author
  return [who, paper.year].filter(Boolean).join(', ')
}
