import type { Paper } from '@/api/types'
import { PdfStateIcon } from '@/components/paper/PdfStateIcon'
import { Spinner } from '@/components/ui/spinner'
import { isActiveJob } from '@/components/jobs/job-labels'
import { usePaperLookup } from '@/hooks/queries/metadata'
import { usePdfComing } from '@/hooks/queries/uploads'

/**
 * Beside the paper's title, only what needs attention (ARA-098): nothing while the PDF is readable, otherwise its state
 * icon with a tooltip. While automatic retrieval brings the PDF it shows as preparing (ARA-086), and an upload waiting
 * for a library-match choice says so. A readable paper whose catalog lookup is still running gets a quiet note, and
 * following the lookup here also refreshes the title in place when it finishes.
 */
export function PaperPdfStatus({ paper }: { paper: Paper }) {
  const lookup = usePaperLookup(paper)
  const coming = usePdfComing(paper)
  const finding = paper.document_status === 'ready' && !!lookup && isActiveJob(lookup)
  if (paper.upload_match) return <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">Matches a library paper</span>
  return (
    <>
      {(coming || paper.document_status !== 'ready') && <PdfStateIcon state={coming ? 'processing' : paper.document_status} />}
      {finding && <span role="status" className="hidden shrink-0 items-center gap-1.5 text-xs text-muted-foreground sm:flex"><Spinner className="size-3" aria-hidden="true" />Finding paper details</span>}
    </>
  )
}
