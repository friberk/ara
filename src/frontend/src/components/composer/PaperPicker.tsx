import { useState } from 'react'
import { AtSign, FileText, X } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { documentStateLabels } from '@/components/feedback/document-state'
import { usePapers } from '@/hooks/queries/papers'

/** Lists library papers; only papers with a processed PDF can be asked about. */
export function PaperPickerList({ onSelect }: { onSelect: (paper: Paper) => void }) {
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
            return (
              <CommandItem key={paper.id} value={`${paper.title ?? 'Untitled paper'} ${paper.id}`} disabled={!ready} onSelect={() => onSelect(paper)} className="items-start">
                <FileText aria-hidden="true" className="mt-0.5" />
                <div className="grid min-w-0 gap-0.5">
                  <span className="line-clamp-2">{paper.title ?? 'Untitled paper'}</span>
                  <span className="text-xs text-muted-foreground">{ready ? [paper.authors[0], paper.year].filter(Boolean).join(', ') || 'Ready to ask' : documentStateLabels[paper.document_status]}</span>
                </div>
              </CommandItem>
            )
          })}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}

export function PaperPicker({ onSelect, disabled }: { onSelect: (paper: Paper) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button type="button" variant="ghost" size="icon-sm" className="rounded-full text-muted-foreground hover:text-foreground" aria-label="Ask about a library paper" disabled={disabled}><AtSign aria-hidden="true" /></Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>Ask about a library paper</TooltipContent>
      </Tooltip>
      <PopoverContent align="start" className="w-[min(26rem,calc(100vw-2rem))] p-0">
        <PaperPickerList onSelect={(paper) => { onSelect(paper); setOpen(false) }} />
      </PopoverContent>
    </Popover>
  )
}

export function PaperContextChip({ paper, onRemove }: { paper: Pick<Paper, 'title'>; onRemove: () => void }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-lg border bg-muted/60 py-1 pr-1 pl-2 text-sm">
      <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="truncate">{paper.title ?? 'Untitled paper'}</span>
      <Button type="button" variant="ghost" size="icon-xs" className="rounded-md" aria-label="Stop asking about this paper" onClick={onRemove}><X aria-hidden="true" /></Button>
    </span>
  )
}
