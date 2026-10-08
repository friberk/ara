import type { Citation } from '@/api/types'
import { CitationChip } from './CitationChip'

export type SourceListProps = {
  citations: Citation[]
  /** Citations from any other document are withheld and reported. */
  documentId: string
  onSelect?: (citation: Citation) => void
  className?: string
}

/** Contract stub (lead): one chip per citation. ARA-035 deduplicates by page and adds keyboard access to excerpts. */
export function SourceList({ citations, documentId, onSelect, className }: SourceListProps) {
  const valid = citations.filter((citation) => citation.document_id === documentId)
  return (
    <>
      {valid.length > 0 && <div className={className} aria-label="Sources">{valid.map((citation, index) => <CitationChip key={`${citation.chunk_id}:${index}`} citation={citation} onSelect={onSelect} />)}</div>}
      {valid.length !== citations.length && <p role="alert" className="text-sm text-destructive">A citation could not be matched to this document.</p>}
    </>
  )
}
