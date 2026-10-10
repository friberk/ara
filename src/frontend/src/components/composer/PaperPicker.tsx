import { useState } from 'react'
import { AtSign, Check, FileText, X } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { documentStateLabels } from '@/components/feedback/document-state'
import { usePapers } from '@/hooks/queries/papers'
import { MAX_CHAT_PAPERS } from '@/lib/paper-names'
import { cn } from '@/lib/utils'

/**
 * Lists library papers; only papers with a processed PDF can be asked about. Papers in `selected` show as added, and
 * choosing one again hands it back to onSelect to remove; once MAX_CHAT_PAPERS are chosen, the rest wait.
 */
export function PaperPickerList({ onSelect, selected = [] }: { onSelect: (paper: Paper) => void; selected?: readonly string[] }) {
  const papers = usePapers('', { pageSize: 50 })
  const items = papers.data?.pages.flatMap((page) => page.items) ?? []
  const full = selected.length >= MAX_CHAT_PAPERS
  return (
    <Command>
      <CommandInput placeholder="Find a paper in your library" />
      <CommandList>
        <CommandEmpty>{papers.isPending ? 'Loading your library…' : 'No matching papers. Save or upload one first.'}</CommandEmpty>
        <CommandGroup heading="Library">
          {items.map((paper) => {
            const ready = paper.document_status === 'ready'
            const added = selected.includes(paper.id)
            const waiting = !added && full
            const detail = added ? 'Added. Choose again to remove.'
              : !ready ? documentStateLabels[paper.document_status]
              : waiting ? `Up to ${MAX_CHAT_PAPERS} papers`
              : [paper.authors[0], paper.year].filter(Boolean).join(', ') || 'Ready to ask'
            return (
              <CommandItem key={paper.id} value={`${paper.title ?? 'Untitled paper'} ${paper.id}`} disabled={!added && (!ready || waiting)} onSelect={() => onSelect(paper)} className="items-start">
                {added ? <Check aria-hidden="true" className="mt-0.5" /> : <FileText aria-hidden="true" className="mt-0.5" />}
                <div className="grid min-w-0 gap-0.5">
                  <span className="line-clamp-2">{paper.title ?? 'Untitled paper'}</span>
                  <span className="text-xs text-muted-foreground">{detail}</span>
                </div>
              </CommandItem>
            )
          })}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}

export function PaperPicker({ onSelect, selected, disabled, open: controlled, onOpenChange, label = 'Ask about a library paper' }: {
  onSelect: (paper: Paper) => void
  /** Ids of the papers already chosen, shown as added. */
  selected?: readonly string[]
  disabled?: boolean
  /** Controlled open state, so typing @ in the composer can open it. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  label?: string
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
      <PopoverContent align="start" className="w-[min(26rem,calc(100vw-2rem))] p-0">
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
