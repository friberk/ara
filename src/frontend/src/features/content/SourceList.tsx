import { useId } from 'react'
import type { Citation } from '@/api/types'
import { cn } from '@/lib/utils'
import { CitationChip } from './CitationChip'
import { citingClaims, stripCitationMarkers } from './remark-citations'

export type SourceListProps = {
  citations: Citation[]
  /** Citations from any other document are withheld and reported. */
  documentId: string
  /**
   * The raw answer or summary these sources support. A page chip hands onSelect the claims whose markers cite that
   * page, or the whole text without markers when none does.
   */
  context?: string
  onSelect?: (citation: Citation, claim?: string) => void
  className?: string
}

/** The pages an answer or summary cites, once each and in page order. */
export function SourceList({ citations, documentId, context, onSelect, className }: SourceListProps) {
  const labelId = useId()
  const valid = citations.filter((citation) => citation.document_id === documentId)
  // The first passage cited on a page represents that page.
  const firstOnPage = new Map<number, Citation>()
  for (const citation of valid) if (!firstOnPage.has(citation.page)) firstOnPage.set(citation.page, citation)
  const pages = [...firstOnPage.values()].sort((a, b) => a.page - b.page)
  const claimFor = (page: number) => {
    if (context === undefined) return undefined
    const chunks = new Set(valid.filter((citation) => citation.page === page).map((citation) => citation.chunk_id.toLowerCase()))
    return citingClaims(context, chunks).join(' ') || stripCitationMarkers(context)
  }
  const mismatch = valid.length !== citations.length
  if (!pages.length && !mismatch) return null
  return (
    <div className={cn('grid gap-2', className)}>
      {pages.length > 0 && (
        <div role="group" aria-labelledby={labelId} className="flex flex-wrap items-center gap-1.5">
          <span id={labelId} className="mr-0.5 text-xs text-muted-foreground">Sources</span>
          {pages.map((citation) => <CitationChip key={citation.chunk_id} citation={citation} claim={claimFor(citation.page)} onSelect={onSelect} />)}
        </div>
      )}
      {mismatch && <p role="alert" className="text-sm text-destructive">A citation could not be matched to this document.</p>}
    </div>
  )
}
