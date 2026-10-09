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
   * The raw answer or summary these sources support. A passage chip hands onSelect the claims whose markers cite that
   * passage, or the whole text without markers when none does.
   */
  context?: string
  onSelect?: (citation: Citation, claim?: string) => void
  className?: string
}

/** The passages an answer or summary cites, once each and in order of their first page. */
export function SourceList({ citations, documentId, context, onSelect, className }: SourceListProps) {
  const labelId = useId()
  const valid = citations.filter((citation) => citation.document_id === documentId)
  // Two passages from one page are two sources; the same passage cited twice is one.
  const byChunk = new Map<string, Citation>()
  for (const citation of valid) if (!byChunk.has(citation.chunk_id.toLowerCase())) byChunk.set(citation.chunk_id.toLowerCase(), citation)
  const passages = [...byChunk.values()].sort((a, b) => a.page - b.page)
  const claimFor = (citation: Citation) => {
    if (context === undefined) return undefined
    return citingClaims(context, new Set([citation.chunk_id.toLowerCase()])).join(' ') || stripCitationMarkers(context)
  }
  const mismatch = valid.length !== citations.length
  if (!passages.length && !mismatch) return null
  return (
    <div className={cn('grid gap-2', className)}>
      {passages.length > 0 && (
        <div role="group" aria-labelledby={labelId} className="flex flex-wrap items-center gap-1.5">
          <span id={labelId} className="mr-0.5 text-xs text-muted-foreground">Sources</span>
          {passages.map((citation) => <CitationChip key={citation.chunk_id} citation={citation} claim={claimFor(citation)} onSelect={onSelect} />)}
        </div>
      )}
      {mismatch && <p role="alert" className="text-sm text-destructive">A citation could not be matched to this document.</p>}
    </div>
  )
}
