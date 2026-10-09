import type { Paper } from '@/api/types'
import { Spinner } from '@/components/ui/spinner'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { isActiveJob } from '@/components/jobs/job-labels'
import { usePaperLookup } from '@/hooks/queries/metadata'

/**
 * The paper's PDF status. A readable paper whose catalog lookup is still running says so in a quiet note beside it;
 * following the lookup here also refreshes the title in place when it finishes (ARA-086).
 */
export function PaperStatusBadge({ paper, className }: { paper: Paper; className?: string }) {
  const lookup = usePaperLookup(paper)
  const finding = paper.document_status === 'ready' && !!lookup && isActiveJob(lookup)
  return (
    <>
      <DocumentStatusBadge state={paper.document_status} className={className} />
      {finding && <span role="status" className="hidden shrink-0 items-center gap-1.5 text-xs text-muted-foreground sm:flex"><Spinner className="size-3" aria-hidden="true" />Finding paper details</span>}
    </>
  )
}
