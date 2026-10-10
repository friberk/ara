import { useId, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { shortCitation } from '@/lib/paper-names'
import { PaperCitation } from './PaperCitation'
import { PdfStateIcon } from './PdfStateIcon'

/** What a pill's citation card needs to know about its paper. */
export type PillPaper = { authors: string[]; year: number | null; venue?: string | null }

/**
 * A paper mentioned in a question, in the composer and in sent questions (ARA-096): a file icon and the paper's title,
 * cut at about 28 characters so the sentence around it stays readable, on the quiet surface of the citation chips and
 * a step smaller than the composer text. Hovering for a moment, or selecting it from the keyboard, opens a card with
 * its short citation and, when the pill cuts the title, the full title. An editable pill (onRemove) also shows a round
 * remove button at its top right while hovered or selected; pressing it keeps focus in the editor. Screen readers hear
 * the title, then the citation as its description, once.
 */
export function PaperPill({ title, paper, selected = false, onRemove }: { title: string; paper?: PillPaper | null; selected?: boolean; onRemove?: () => void }) {
  const description = useId()
  const label = useRef<HTMLSpanElement>(null)
  const [hovered, setHovered] = useState(false)
  const [hoverOpen, setHoverOpen] = useState(false)
  // Escape closes the card until the pill is hovered or selected again.
  const [dismissed, setDismissed] = useState(false)
  const [wasSelected, setWasSelected] = useState(selected)
  const [truncated, setTruncated] = useState(false)
  if (selected !== wasSelected) {
    setWasSelected(selected)
    setDismissed(false)
  }
  const citation = paper ? shortCitation(paper) : ''
  const active = hovered || selected
  const open = (hoverOpen || selected) && !dismissed && (!!citation || truncated)
  const measure = (element: HTMLSpanElement | null) => setTruncated(!!element && element.scrollWidth > element.clientWidth)
  return (
    <HoverCard open={open} onOpenChange={setHoverOpen} openDelay={300} closeDelay={150}>
      <HoverCardTrigger asChild>
        <span
          role={onRemove ? 'group' : 'img'}
          aria-roledescription="paper"
          aria-label={title}
          aria-describedby={citation ? description : undefined}
          data-active={active}
          onPointerEnter={() => { setHovered(true); setDismissed(false); measure(label.current) }}
          onPointerLeave={() => setHovered(false)}
          className="relative mx-px inline-flex max-w-full items-baseline gap-1 rounded-sm bg-muted px-1.5 align-baseline text-[13px] leading-5 font-medium whitespace-nowrap text-foreground transition-[background-color,box-shadow] duration-150 ease-out data-[active=true]:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_8%)] data-[active=true]:ring-1 data-[active=true]:ring-foreground/15"
        >
          <PdfStateIcon state="ready" decorative tooltip={false} className="size-3.5 self-center [&>svg]:size-3.5" />
          <span ref={(element) => { label.current = element; if (selected) measure(element) }} aria-hidden="true" className="min-w-0 max-w-[28ch] truncate">{title}</span>
          {citation && <span id={description} hidden>{citation}</span>}
          {onRemove && active && (
            <button
              type="button"
              tabIndex={-1}
              aria-label={`Remove ${title}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={(event) => { event.stopPropagation(); onRemove() }}
              className="absolute -top-1.5 -right-1.5 flex size-4 items-center justify-center rounded-full bg-background text-foreground shadow-[0_1px_2px_rgb(0_0_0/0.16)] ring-1 ring-border transition-colors outline-none after:absolute after:-inset-1.5 hover:bg-muted"
            >
              <X aria-hidden="true" className="size-2.5" strokeWidth={2.5} />
            </button>
          )}
        </span>
      </HoverCardTrigger>
      <HoverCardContent side="top" align="start" sideOffset={6} collisionPadding={12} onEscapeKeyDown={() => setDismissed(true)} className="grid w-auto max-w-[min(20rem,calc(100vw-1.5rem))] gap-1 px-3 py-2">
        {truncated && <p className="text-sm leading-snug font-medium text-pretty">{title}</p>}
        {paper && <PaperCitation paper={paper} />}
      </HoverCardContent>
    </HoverCard>
  )
}
