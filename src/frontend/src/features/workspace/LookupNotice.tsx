import { RotateCcw } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { isActiveJob } from '@/components/jobs/job-labels'
import { usePaperLookup } from '@/hooks/queries/metadata'
import { useLookUpAgain } from '@/hooks/queries/papers'
import { canLookUp } from '@/features/research/paper-format'

/**
 * Looks the paper up again in the metadata source at any time (ARA-095). A lookup that ran out of attempts says why
 * and kept the PDF's details (ARA-086); one that is running shows here until it settles. In the ⓘ sheet (ARA-097) the
 * other details actions, given as children, share its row.
 */
export function LookupNotice({ paper, children }: { paper: Paper; children?: React.ReactNode }) {
  const lookup = usePaperLookup(paper)
  const again = useLookUpAgain(paper.id)
  const available = canLookUp(paper)
  const running = again.isPending || (!!lookup && isActiveJob(lookup))
  if (!available && !children) return null
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {children}
        {available && <Button variant="outline" size="sm" disabled={running} onClick={() => again.mutate()}><RotateCcw data-icon="inline-start" aria-hidden="true" />{running ? 'Looking up…' : 'Look up again'}</Button>}
      </div>
      {available && <p className="text-xs text-pretty text-muted-foreground">Refreshes the details from the metadata source. Fields you edited stay as they are.</p>}
      {available && lookup?.state === 'failed' && <p className="text-sm text-pretty text-muted-foreground">{lookup.error?.message ?? 'The paper’s details could not be looked up, so the details read from the PDF were kept.'}</p>}
      <ErrorNotice error={again.error} />
    </div>
  )
}
