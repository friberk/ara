import { LoaderCircle } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { isActiveJob } from '@/components/jobs/job-labels'
import { usePaperLookup } from '@/hooks/queries/metadata'
import { cn } from '@/lib/utils'

/**
 * The paper's PDF status, or, once the PDF is readable, the catalog lookup still filling in its details. Following
 * the lookup here also refreshes the title in place when it finishes (ARA-086).
 */
export function PaperStatusBadge({ paper, className }: { paper: Paper; className?: string }) {
  const lookup = usePaperLookup(paper)
  if (paper.document_status !== 'ready' || !lookup || !isActiveJob(lookup)) return <DocumentStatusBadge state={paper.document_status} className={className} />
  return <Badge variant="secondary" className={cn('bg-warning-muted font-normal text-warning', className)}><LoaderCircle data-icon="inline-start" aria-hidden="true" className="motion-safe:animate-spin" />Finding paper details</Badge>
}
