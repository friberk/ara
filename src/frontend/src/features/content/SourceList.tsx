import { useId } from 'react'
import type { Citation } from '@/api/types'
import { cn } from '@/lib/utils'
import { CitationChip } from './CitationChip'

export type SourceListProps = {
  citations: Citation[]
  /** Citations from any other document are withheld and reported. */
  documentId: string
  onSelect?: (citation: Citation) => void
  className?: string
}

/** The pages an answer or summary cites, once each and in page order. */
export function SourceList({ citations, documentId, onSelect, className }: SourceListProps) {
  const labelId = useId()
  const valid = citations.filter((citation) => citation.document_id === documentId)
  // The first passage cited on a page represents that page.
  const firstOnPage = new Map<number, Citation>()
  for (const citation of valid) if (!firstOnPage.has(citation.page)) firstOnPage.set(citation.page, citation)
  const pages = [...firstOnPage.values()].sort((a, b) => a.page - b.page)
  const mismatch = valid.length !== citations.length
  if (!pages.length && !mismatch) return null
  return (
    <div className={cn('grid gap-2', className)}>
      {pages.length > 0 && (
        <div role="group" aria-labelledby={labelId} className="flex flex-wrap items-center gap-1.5">
          <span id={labelId} className="mr-0.5 text-xs text-muted-foreground">Sources</span>
          {pages.map((citation) => <CitationChip key={citation.chunk_id} citation={citation} onSelect={onSelect} />)}
        </div>
      )}
      {mismatch && <p role="alert" className="text-sm text-destructive">A citation could not be matched to this document.</p>}
    </div>
  )
}
