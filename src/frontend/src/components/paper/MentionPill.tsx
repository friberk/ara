import { FileText } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { usePaper } from '@/hooks/queries/papers'
import type { MentionSpan } from '@/lib/mentions'
import { citationText } from '@/lib/paper-names'
import { PaperCitation } from './PaperCitation'
import { pillClass, pillIconClass, pillLabelClass } from './pill'

/**
 * A paper a sent question mentioned, as the same pill the composer showed (ARA-096). Its accessible name is the
 * paper's citation once the paper loads, its label until then or if the paper was deleted; hovering names it in full.
 */
export function MentionPill({ mention }: { mention: MentionSpan }) {
  const paper = usePaper(mention.paper_id).data
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span role="img" aria-roledescription="paper" aria-label={paper ? citationText(paper) : mention.label} className={pillClass}>
          <FileText aria-hidden="true" className={pillIconClass} />
          <span className={pillLabelClass}>{mention.label}</span>
        </span>
      </TooltipTrigger>
      {paper && (
        <TooltipContent className="grid gap-0.5">
          <span className="line-clamp-2 font-medium">{paper.title ?? 'Untitled paper'}</span>
          <PaperCitation paper={paper} className="text-background/80" />
        </TooltipContent>
      )}
    </Tooltip>
  )
}
