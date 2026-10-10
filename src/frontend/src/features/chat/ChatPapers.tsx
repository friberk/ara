import { useNavigate } from 'react-router-dom'
import type { IncludedPaper } from '@/api/types'
import { PaperPill, type PillPaper } from '@/components/paper/PaperPill'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useOptionalWorkspace } from '@/features/workspace/workspace-context'
import { usePaperList } from '@/hooks/queries/papers'
import { VISIBLE_PAPER_CHIPS } from '@/lib/paper-names'

type ChatPapersProps = { papers: IncludedPaper[]; onRemove: (paperId: string) => void; removing?: string | null }

/**
 * The papers a chat covers, as the composer's pills above the thread (ARA-110), once the chat covers more than one: a
 * click opens the paper's PDF in a reader tab (its own page outside the workspace), and the corner × removes it from the
 * chat. A chat may include any number of papers: beyond VISIBLE_PAPER_CHIPS the rest collapse into a "+N" pill whose
 * list shows them as the same pills. A single paper has no row, so the last paper can never be removed.
 */
export function ChatPapers({ papers, onRemove, removing }: ChatPapersProps) {
  const workspace = useOptionalWorkspace()
  const navigate = useNavigate()
  const several = papers.length > 1
  // The same queries name the cited papers (useChatSources), so each paper loads once.
  const details = new Map(usePaperList(several ? papers.map((paper) => paper.paper_id) : []).map((paper) => [paper.id, paper]))
  if (!several) return null
  const hidden = papers.slice(VISIBLE_PAPER_CHIPS)
  const open = (paperId: string) => (workspace ? workspace.showPaper(paperId) : navigate(`/papers/${paperId}`))
  const pill = (paper: IncludedPaper) => {
    const detail: PillPaper = details.get(paper.paper_id) ?? { authors: paper.first_author ? [paper.first_author] : [], year: paper.year }
    return (
      <PaperPill
        title={paper.title?.trim() || 'Untitled paper'}
        paper={detail}
        onActivate={() => open(paper.paper_id)}
        onRemove={() => onRemove(paper.paper_id)}
        removeDisabled={removing === paper.paper_id}
      />
    )
  }
  return (
    // Opaque, so the thread scrolling beneath never shows through; the thread draws the hairline (ARA-097).
    <ul aria-label="Papers in this conversation" className="flex flex-wrap items-center gap-x-2 gap-y-2.5 bg-background px-4 pt-2 pb-2.5">
      {papers.slice(0, VISIBLE_PAPER_CHIPS).map((paper) => <li key={paper.paper_id} className="flex max-w-full min-w-0">{pill(paper)}</li>)}
      {hidden.length > 0 && (
        <li className="flex">
          <Popover>
            <PopoverTrigger asChild>
              <button type="button" aria-label={`+${hidden.length} more papers`} className="inline-flex h-5 cursor-pointer items-center rounded-sm bg-muted px-1.5 text-[13px] font-medium text-foreground tabular transition-colors outline-none hover:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_8%)] focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_8%)]">
                +{hidden.length}
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[min(22rem,calc(100vw-2rem))] p-3">
              <ul aria-label="More papers in this conversation" className="flex max-h-80 flex-col items-start gap-2.5 overflow-y-auto p-1">
                {hidden.map((paper) => <li key={paper.paper_id} className="flex max-w-full min-w-0">{pill(paper)}</li>)}
              </ul>
            </PopoverContent>
          </Popover>
        </li>
      )}
    </ul>
  )
}
