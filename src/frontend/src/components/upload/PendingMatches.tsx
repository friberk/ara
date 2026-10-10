import { useId } from 'react'
import { FileText } from 'lucide-react'
import { toast } from 'sonner'
import { usePendingMatches } from '@/hooks/queries/uploads'
import { cn } from '@/lib/utils'
import { attachedNote } from './match-copy'
import { MatchDecision } from './MatchDecision'

/**
 * Uploads that matched a library paper and still wait for a choice, from this visit or an earlier one. They are not
 * library papers until resolved (ARA-086). `hidden` leaves out the ones the upload list already shows.
 */
export function PendingMatches({ hidden = [], className }: { hidden?: string[]; className?: string }) {
  const headingId = useId()
  const pending = usePendingMatches()
  const items = (pending.data?.items ?? []).filter((paper) => paper.upload_match && !hidden.includes(paper.id))
  if (!items.length) return null
  return (
    <section aria-labelledby={headingId} className={cn('rounded-xl border', className)}>
      <h2 id={headingId} className="flex min-h-11 items-center border-b px-4 py-1.5 text-sm font-medium">Needs your choice</h2>
      <ul className="divide-y">
        {items.map((paper) => paper.upload_match && (
          <li key={paper.id} className="grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-x-3 gap-y-1 px-4 py-3">
            <FileText className="mt-0.5 size-4 text-muted-foreground" aria-hidden="true" />
            <p className="truncate text-sm font-medium">{paper.file_name ?? 'Uploaded PDF'}</p>
            <MatchDecision
              paper={{ ...paper, upload_match: paper.upload_match }}
              variant="row"
              className="col-start-2"
              onResolved={(decision) => toast(decision === 'discard' ? 'Upload discarded.' : attachedNote(paper.upload_match!))}
            />
          </li>
        ))}
      </ul>
    </section>
  )
}
