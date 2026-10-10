import { LoaderCircle } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { isActiveJob } from '@/components/jobs/job-labels'
import { usePaperLookup } from '@/hooks/queries/metadata'
import { usePdfComing } from '@/hooks/queries/uploads'
import { cn } from '@/lib/utils'

/**
 * The paper's PDF status: "Getting PDF" while automatic retrieval brings it, and a note when an upload waits for a
 * library-match choice (ARA-086). A readable paper whose catalog lookup is still running says so in a quiet note beside it;
 * following the lookup here also refreshes the title in place when it finishes (ARA-086).
 */
export function PaperStatusBadge({ paper, className }: { paper: Paper; className?: string }) {
  const lookup = usePaperLookup(paper)
  const coming = usePdfComing(paper)
  const finding = paper.document_status === 'ready' && !!lookup && isActiveJob(lookup)
  if (paper.upload_match) return <Badge variant="secondary" className={cn('font-normal text-muted-foreground', className)}>Matches a library paper</Badge>
  if (coming) return <Badge variant="secondary" className={cn('bg-warning-muted font-normal text-warning', className)}><LoaderCircle data-icon="inline-start" aria-hidden="true" className="motion-safe:animate-spin" />Getting PDF</Badge>
  return (
    <>
      <DocumentStatusBadge state={paper.document_status} className={className} />
      {finding && <span role="status" className="hidden shrink-0 items-center gap-1.5 text-xs text-muted-foreground sm:flex"><Spinner className="size-3" aria-hidden="true" />Finding paper details</span>}
    </>
  )
}
