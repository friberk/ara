import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, X } from 'lucide-react'
import type { IncludedPaper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { SummaryCard } from '@/features/summary'
import { usePaper } from '@/hooks/queries/papers'
import { paperByline } from '@/lib/paper-names'

const titleOf = (paper: Pick<IncludedPaper, 'title'>) => paper.title?.trim() || 'Untitled paper'

/** A paper's summary on demand, from its chip, instead of a summary card per paper in the thread. */
function PaperSummaryDialog({ paper, onClose }: { paper: IncludedPaper; onClose: () => void }) {
  const detail = usePaper(paper.paper_id)
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="pr-6 text-balance">{titleOf(paper)}</DialogTitle>
          <DialogDescription>{detail.data ? paperByline(detail.data) || 'Paper summary' : 'Paper summary'}</DialogDescription>
        </DialogHeader>
        {detail.data ? <SummaryCard paper={detail.data} /> : <Skeleton className="h-32 w-full rounded-2xl" />}
        <DialogFooter>
          <Button asChild variant="outline"><Link to={`/papers/${paper.paper_id}`}>Open paper</Link></Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * The papers a chat covers, as chips above the thread (ARA-088). A chip opens that paper's summary; the last paper
 * cannot be removed.
 */
export function ChatPapers({ papers, onRemove, removing }: { papers: IncludedPaper[]; onRemove: (paperId: string) => void; removing?: string | null }) {
  const [open, setOpen] = useState<IncludedPaper | null>(null)
  const removable = papers.length > 1
  return (
    <>
      <ul aria-label="Papers in this conversation" className="flex flex-wrap gap-1.5 px-4 pb-2">
        {papers.map((paper) => (
          <li key={paper.paper_id} className="flex max-w-full min-w-0">
            <span className="inline-flex max-w-[18rem] min-w-0 items-center rounded-lg border bg-muted/60 text-sm">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" onClick={() => setOpen(paper)} className="inline-flex min-w-0 items-center gap-1.5 rounded-lg py-1 pr-1 pl-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
                    <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="truncate">{titleOf(paper)}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom">Show summary</TooltipContent>
              </Tooltip>
              {removable ? (
                <Button type="button" variant="ghost" size="icon-xs" className="mr-0.5 rounded-md" aria-label={`Remove ${titleOf(paper)} from this conversation`} disabled={removing === paper.paper_id} onClick={() => onRemove(paper.paper_id)}><X aria-hidden="true" /></Button>
              ) : <span className="w-1.5" aria-hidden="true" />}
            </span>
          </li>
        ))}
      </ul>
      {open && <PaperSummaryDialog paper={open} onClose={() => setOpen(null)} />}
    </>
  )
}
