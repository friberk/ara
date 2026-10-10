import type { Paper } from '@/api/types'
import { ReaderDocuments, type ReaderTab } from './ReaderDocuments'

type ReaderProps = {
  paper: Paper
  tabs: ReaderTab[]
  active: string
  onActivate: (paperId: string) => void
  onClose: (paperId: string) => void
  onShowCurrent: (paperId: string) => void
}

/**
 * The reader, on desktop beside the conversation and on narrow screens as the PDF view (ARA-097). It always shows the
 * PDF: the open file with its controls bar, or, until the paper has one, the ways to get it. The paper's details are
 * behind ⓘ in the header, not in a tab here.
 */
export function ReaderPanel({ paper, ...documents }: ReaderProps) {
  return (
    // Focusable from script only: removing the PDF hands focus here when its menu disappears (ARA-097).
    <section aria-label="PDF reader" tabIndex={-1} className="h-full min-h-0 outline-none">
      <ReaderDocuments paper={paper} {...documents} />
    </section>
  )
}
