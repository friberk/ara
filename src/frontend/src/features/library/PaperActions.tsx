import { useEffect, useState } from 'react'
import { MoreHorizontal, Pencil, RotateCcw, Trash2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useJob } from '@/hooks/queries/jobs'
import { useLookUpAgain } from '@/hooks/queries/papers'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import { canLookUp, paperName } from '@/features/research/paper-format'
import { EditDetailsDialog } from '@/features/workspace/BibliographyEditor'
import { DeletePapersDialog } from './DeletePapersDialog'

/** Refreshes the library when a lookup started here settles, so improved details appear without a reload. */
function LookupFollower({ jobId, onSettled }: { jobId: string; onSettled: () => void }) {
  const job = useJob(jobId)
  const client = useQueryClient()
  const settled = job.data?.state === 'completed' || job.data?.state === 'failed'
  useEffect(() => {
    if (!settled) return
    void client.invalidateQueries({ queryKey: queryKeys.papers.all })
    onSettled()
  }, [settled, client, onSettled])
  return null
}

/**
 * A paper's actions: edit its details, look it up again, delete it. The same menu sits on each Library row and in the
 * workspace header, so both places behave alike.
 */
export function PaperActions({ paper, onDeleted, className }: { paper: Paper; onDeleted?: () => void; className?: string }) {
  const [dialog, setDialog] = useState<'edit' | 'delete' | null>(null)
  const [following, setFollowing] = useState<string | null>(null)
  const lookup = useLookUpAgain(paper.id)
  const name = paperName(paper)
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={`Actions for “${name}”`} className={cn('text-muted-foreground', className)}><MoreHorizontal aria-hidden="true" /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem onSelect={() => setDialog('edit')}><Pencil aria-hidden="true" />Edit details</DropdownMenuItem>
          {canLookUp(paper) && (
            <DropdownMenuItem
              disabled={lookup.isPending || following !== null}
              onSelect={() => lookup.mutate(undefined, {
                onSuccess: (job) => { setFollowing(job.id); toast('Looking up the paper’s details. Fields you edited stay as they are.') },
                onError: (error) => toast.error(error.message),
              })}
            >
              <RotateCcw aria-hidden="true" />Look up details again
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}><Trash2 aria-hidden="true" />Delete…</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {following && <LookupFollower jobId={following} onSettled={() => setFollowing(null)} />}
      {dialog === 'edit' && <EditDetailsDialog paper={paper} onClose={() => setDialog(null)} />}
      <DeletePapersDialog papers={[paper]} open={dialog === 'delete'} onOpenChange={(open) => { if (!open) setDialog(null) }} onDeleted={onDeleted} />
    </>
  )
}
