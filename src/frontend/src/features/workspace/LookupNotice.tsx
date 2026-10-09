import { RotateCcw } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useRetryJob } from '@/hooks/queries/jobs'
import { usePaperLookup } from '@/hooks/queries/metadata'

/** A catalog lookup that ran out of attempts kept the PDF's details; it can be run again from here (ARA-086). */
export function LookupNotice({ paper }: { paper: Paper }) {
  const lookup = usePaperLookup(paper)
  const retry = useRetryJob()
  if (lookup?.state !== 'failed') return null
  return (
    <div className="grid justify-items-start gap-2">
      <p className="text-sm text-pretty text-muted-foreground">{lookup.error?.message ?? 'The paper’s details could not be looked up, so the details read from the PDF were kept.'}</p>
      <Button variant="outline" size="sm" disabled={retry.isPending} onClick={() => retry.mutate(lookup.id)}><RotateCcw data-icon="inline-start" aria-hidden="true" />{retry.isPending ? 'Looking up…' : 'Look up again'}</Button>
      <ErrorNotice error={retry.error} />
    </div>
  )
}
