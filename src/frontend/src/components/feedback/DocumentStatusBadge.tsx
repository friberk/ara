import { CircleAlert, CircleCheck, FileQuestion, LoaderCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { DocumentState } from '@/api/types'
import { cn } from '@/lib/utils'
import { documentStateLabels } from './document-state'

const tone: Record<DocumentState, string> = {
  metadata_only: 'bg-muted text-muted-foreground',
  processing: 'bg-warning-muted text-warning',
  ready: 'bg-success-muted text-success',
  failed: 'bg-destructive/10 text-destructive',
}
const icons = { metadata_only: FileQuestion, processing: LoaderCircle, ready: CircleCheck, failed: CircleAlert }

export function DocumentStatusBadge({ state, className }: { state: DocumentState; className?: string }) {
  const Icon = icons[state]
  return <Badge variant="secondary" className={cn('font-normal', tone[state], className)}><Icon data-icon="inline-start" aria-hidden="true" className={state === 'processing' ? 'motion-safe:animate-spin' : undefined} />{documentStateLabels[state]}</Badge>
}
