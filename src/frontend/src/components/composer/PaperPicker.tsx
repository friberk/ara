import { useState } from 'react'
import { AtSign } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { PaperCitation } from '@/components/paper/PaperCitation'
import { PdfStateIcon } from '@/components/paper/PdfStateIcon'
import { pdfStateLabels } from '@/components/paper/pdf-state'
import { usePapers } from '@/hooks/queries/papers'

/**
 * Lists library papers; only papers with a processed PDF can be asked about. Each row gives the title and a short
 * citation (authors, year, venue) beside an icon for the PDF's state. Papers in `selected` are checked the stock
 * cmdk way, and choosing one again hands it back to onSelect to remove. Search matches the title, author surnames, year
 * and venue. A conversation may include any number of papers (ARA-088).
 */
export function PaperPickerList({ onSelect, selected = [], placeholder = 'Find a paper in your library' }: { onSelect: (paper: Paper) => void; selected?: readonly string[]; placeholder?: string }) {
  const papers = usePapers('', { pageSize: 50 })
  const items = papers.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <Command>
      <CommandInput placeholder={placeholder} />
      <CommandList>
        <CommandEmpty>{papers.isPending ? 'Loading your library…' : 'No matching papers. Save or upload one first.'}</CommandEmpty>
        <CommandGroup heading="Library">
          {items.map((paper) => {
            const ready = paper.document_status === 'ready'
            const added = selected.includes(paper.id)
            const blocked = !added && !ready
            const keywords = [...paper.authors, paper.year ? String(paper.year) : '', paper.venue ?? ''].filter(Boolean)
            return (
              <CommandItem key={paper.id} value={`${paper.title ?? 'Untitled paper'} ${paper.id}`} keywords={keywords} disabled={blocked} data-checked={added} aria-checked={added} onSelect={() => onSelect(paper)} className="items-start">
                {/* A blocked row names why in its option name; the icon is then decorative so the state is not read twice. */}
                <PdfStateIcon state={paper.document_status} focusable={false} decorative={blocked} className="mt-0.5" />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="line-clamp-2 text-sm">{paper.title ?? 'Untitled paper'}</span>
                  <PaperCitation paper={paper} />
                </div>
                {blocked && <span className="sr-only">{pdfStateLabels[paper.document_status]}. {paper.document_status === 'processing' ? 'You can ask once it is ready.' : 'Add one to ask about this paper.'}</span>}
              </CommandItem>
            )
          })}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}

export function PaperPicker({ onSelect, selected, disabled, open: controlled, onOpenChange, label = 'Ask about a library paper', refocus, mentioning }: {
  onSelect: (paper: Paper) => void
  /** Ids of the papers already chosen, shown as added. */
  selected?: readonly string[]
  disabled?: boolean
  /** Controlled open state, so typing @ in the composer can open it. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  label?: string
  /** Where focus goes when the picker closes; by default it returns to the @ button. */
  refocus?: () => void
  /** Opened by typing @: the picker mentions a paper rather than adding or removing it. */
  mentioning?: boolean
}) {
  const [uncontrolled, setUncontrolled] = useState(false)
  const open = controlled ?? uncontrolled
  const setOpen = (next: boolean) => { setUncontrolled(next); onOpenChange?.(next) }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button type="button" variant="ghost" size="icon-sm" className="rounded-full text-muted-foreground hover:text-foreground" aria-label={label} disabled={disabled}><AtSign aria-hidden="true" /></Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
      <PopoverContent align="start" className="w-[min(26rem,calc(100vw-2rem))] p-0" onCloseAutoFocus={refocus && ((event) => { event.preventDefault(); refocus() })}>
        <PaperPickerList selected={selected} placeholder={mentioning ? 'Mention a paper' : undefined} onSelect={(paper) => { onSelect(paper); setOpen(false) }} />
      </PopoverContent>
    </Popover>
  )
}
