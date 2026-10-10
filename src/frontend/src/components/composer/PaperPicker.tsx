import { useState } from 'react'
import { AtSign, FileText, X } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { documentStateLabels } from '@/components/feedback/document-state'
import { usePapers } from '@/hooks/queries/papers'
import { citationLine, VISIBLE_PAPER_CHIPS } from '@/lib/paper-names'
import { cn } from '@/lib/utils'

/**
 * Lists library papers; only papers with a processed PDF can be asked about. Each row gives the title and a short
 * citation (authors, year, venue), or the PDF's status while it is not ready. Papers in `selected` are checked the stock
 * cmdk way, and choosing one again hands it back to onSelect to remove. Search matches the title, author surnames, year
 * and venue. A conversation may include any number of papers (ARA-088).
 */
export function PaperPickerList({ onSelect, selected = [] }: { onSelect: (paper: Paper) => void; selected?: readonly string[] }) {
  const papers = usePapers('', { pageSize: 50 })
  const items = papers.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <Command>
      <CommandInput placeholder="Find a paper in your library" />
      <CommandList>
        <CommandEmpty>{papers.isPending ? 'Loading your library…' : 'No matching papers. Save or upload one first.'}</CommandEmpty>
        <CommandGroup heading="Library">
          {items.map((paper) => {
            const ready = paper.document_status === 'ready'
            const added = selected.includes(paper.id)
            const detail = ready ? citationLine(paper) : documentStateLabels[paper.document_status]
            const keywords = [...paper.authors, paper.year ? String(paper.year) : '', paper.venue ?? ''].filter(Boolean)
            return (
              <CommandItem key={paper.id} value={`${paper.title ?? 'Untitled paper'} ${paper.id}`} keywords={keywords} disabled={!added && !ready} data-checked={added} aria-checked={added} onSelect={() => onSelect(paper)} className="items-start">
                <FileText aria-hidden="true" className="mt-0.5" />
                <div className="grid min-w-0 gap-0.5">
                  <span className="line-clamp-2">{paper.title ?? 'Untitled paper'}</span>
                  {detail && <span className="truncate text-xs text-muted-foreground">{detail}</span>}
                </div>
              </CommandItem>
            )
          })}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}

export function PaperPicker({ onSelect, selected, disabled, open: controlled, onOpenChange, label = 'Ask about a library paper', refocus }: {
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
        <PaperPickerList selected={selected} onSelect={(paper) => { onSelect(paper); setOpen(false) }} />
      </PopoverContent>
    </Popover>
  )
}

export function PaperContextChip({ paper, onRemove, removeLabel = 'Stop asking about this paper' }: { paper: Pick<Paper, 'title'>; onRemove?: () => void; removeLabel?: string }) {
  return (
    <span className={cn('inline-flex max-w-full items-center gap-1.5 rounded-lg border bg-muted/60 py-1 pl-2 text-sm', onRemove ? 'pr-1' : 'pr-2')}>
      <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="truncate">{paper.title ?? 'Untitled paper'}</span>
      {onRemove && <Button type="button" variant="ghost" size="icon-xs" className="rounded-md" aria-label={removeLabel} onClick={onRemove}><X aria-hidden="true" /></Button>}
    </span>
  )
}

/**
 * The papers chosen in a composer as removable chips. Beyond VISIBLE_PAPER_CHIPS they collapse into "+N more", which
 * lists every chosen paper with its own remove button.
 */
export function PaperChips({ papers, onRemove }: { papers: Pick<Paper, 'id' | 'title'>[]; onRemove: (paper: Pick<Paper, 'id' | 'title'>) => void }) {
  const several = papers.length > 1
  const label = (paper: Pick<Paper, 'title'>) => `Remove ${paper.title ?? 'Untitled paper'}`
  const hidden = papers.length - VISIBLE_PAPER_CHIPS
  return (
    <>
      {papers.slice(0, VISIBLE_PAPER_CHIPS).map((paper) => <PaperContextChip key={paper.id} paper={paper} removeLabel={several ? label(paper) : undefined} onRemove={() => onRemove(paper)} />)}
      {hidden > 0 && (
        <Popover>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" size="sm" className="h-auto rounded-lg py-1 font-normal text-muted-foreground">+{hidden} more</Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-[min(22rem,calc(100vw-2rem))] p-1">
            <ul aria-label="Chosen papers" className="max-h-72 overflow-y-auto">
              {papers.map((paper) => (
                <li key={paper.id} className="flex items-center gap-2 rounded-md py-1 pr-1 pl-2 text-sm hover:bg-muted">
                  <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{paper.title ?? 'Untitled paper'}</span>
                  <Button type="button" variant="ghost" size="icon-xs" aria-label={label(paper)} onClick={() => onRemove(paper)}><X aria-hidden="true" /></Button>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      )}
    </>
  )
}
