import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, X } from 'lucide-react'
import type { IncludedPaper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { SummaryCard } from '@/features/summary'
import { usePaper } from '@/hooks/queries/papers'
import { paperByline, VISIBLE_PAPER_CHIPS } from '@/lib/paper-names'

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

function RemoveButton({ paper, removing, onRemove }: { paper: IncludedPaper; removing?: string | null; onRemove: (paperId: string) => void }) {
  return (
    <Button type="button" variant="ghost" size="icon-xs" className="mr-0.5 rounded-md" aria-label={`Remove ${titleOf(paper)} from this conversation`} disabled={removing === paper.paper_id} onClick={() => onRemove(paper.paper_id)}><X aria-hidden="true" /></Button>
  )
}

/**
 * The papers a chat covers, as chips above the thread (ARA-088). A chip opens that paper's summary; the last paper
 * cannot be removed. A chat may include any number of papers: beyond VISIBLE_PAPER_CHIPS the rest collapse into
 * "+N more", which lists every paper with its summary and remove buttons.
 */
export function ChatPapers({ papers, onRemove, removing }: { papers: IncludedPaper[]; onRemove: (paperId: string) => void; removing?: string | null }) {
  const [open, setOpen] = useState<IncludedPaper | null>(null)
  const removable = papers.length > 1
  const hidden = papers.length - VISIBLE_PAPER_CHIPS
  return (
    <>
      <ul aria-label="Papers in this conversation" className="flex flex-wrap gap-1.5 px-4 pb-2">
        {papers.slice(0, VISIBLE_PAPER_CHIPS).map((paper) => (
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
              {removable ? <RemoveButton paper={paper} removing={removing} onRemove={onRemove} /> : <span className="w-1.5" aria-hidden="true" />}
            </span>
          </li>
        ))}
        {hidden > 0 && (
          <li className="flex">
            <Popover>
              <PopoverTrigger asChild>
                <Button type="button" variant="outline" size="sm" className="h-auto rounded-lg py-1 font-normal text-muted-foreground">+{hidden} more</Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))] p-1">
                <ul aria-label="All papers in this conversation" className="max-h-80 overflow-y-auto">
                  {papers.map((paper) => (
                    <li key={paper.paper_id} className="flex items-center gap-1 rounded-md text-sm hover:bg-muted">
                      <button type="button" onClick={() => setOpen(paper)} className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1.5 pl-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                        <span className="truncate">{titleOf(paper)}</span>
                      </button>
                      <RemoveButton paper={paper} removing={removing} onRemove={onRemove} />
                    </li>
                  ))}
                </ul>
              </PopoverContent>
            </Popover>
          </li>
        )}
      </ul>
      {open && <PaperSummaryDialog paper={open} onClose={() => setOpen(null)} />}
    </>
  )
}
