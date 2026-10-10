import type { Citation } from '@/api/types'

type Located = Pick<Citation, 'page' | 'page_end'>

/** Whether a passage runs onto a later page than the one it starts on. */
export const spansPages = (citation: Located) => !!citation.page_end && citation.page_end > citation.page

/** "6", or "5–6" for a passage that runs onto the next page. */
export const pageSpan = (citation: Located) => (spansPages(citation) ? `${citation.page}–${citation.page_end}` : `${citation.page}`)

/** The visible chip label and copied-text reference: "p. 6" or "p. 5–6". */
export const pageLabel = (citation: Located) => `p. ${pageSpan(citation)}`

/** The visible chip label, naming the paper in a chat over several papers: "Smith 2023 · p. 4". */
export const sourceLabel = (citation: Located, paper?: string) => (paper ? `${paper} · ${pageLabel(citation)}` : pageLabel(citation))

/**
 * The chip's accessible name. The innermost heading tells apart two passages cited from one page; the full heading
 * path is in the preview. In a chat over several papers it names the paper first.
 */
export function sourceName(citation: Pick<Citation, 'page' | 'page_end' | 'section'>, paper?: string) {
  const heading = citation.section?.split('>').at(-1)?.trim()
  return `Source, ${paper ? `${paper}, ` : ''}${spansPages(citation) ? 'pages' : 'page'} ${pageSpan(citation)}${heading ? `, ${heading}` : ''}`
}
