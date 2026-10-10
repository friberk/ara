import { useState } from 'react'
import { ChevronDown, ChevronUp, MoveHorizontal, ZoomIn, ZoomOut } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { PdfControls } from './pdf-controls'
import { PdfMenu } from './PdfMenu'

function ToolButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button type="button" variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-foreground" aria-label={label} onClick={onClick} disabled={disabled}>{children}</Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

/**
 * Page position, paging and zoom in the middle, the PDF menu at the end (ARA-097). The page field accepts a number to
 * jump to. `managed` is the workspace paper when this is its current PDF, which the menu can then replace or remove.
 */
export function PdfToolbar({ controls, documentId, managed, className }: { controls: PdfControls; documentId: string; managed?: Paper; className?: string }) {
  const [draft, setDraft] = useState<string | null>(null)
  const { page, numPages } = controls
  function commit() {
    if (draft) controls.goTo(Number(draft))
    setDraft(null)
  }
  return (
    <div role="toolbar" aria-label="PDF controls" className={cn('grid w-full grid-cols-[1fr_auto_1fr] items-center', className)}>
      <div className="col-start-2 flex items-center gap-0.5">
        <ToolButton label="Previous page" onClick={() => controls.goTo(page - 1)} disabled={!numPages || page <= 1}><ChevronUp aria-hidden="true" /></ToolButton>
        <div className="flex items-center gap-1.5 px-1 text-sm">
          <Input
            aria-label="Page number"
            inputMode="numeric"
            autoComplete="off"
            className="h-7 w-10 px-1 text-center tabular md:text-sm"
            value={draft ?? String(page)}
            disabled={!numPages}
            onFocus={(event) => event.currentTarget.select()}
            onChange={(event) => setDraft(event.target.value.replace(/\D/g, '').slice(0, 4))}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === 'Enter') { event.preventDefault(); commit() }
              if (event.key === 'Escape') setDraft(null)
            }}
          />
          <span className="tabular whitespace-nowrap text-muted-foreground">/ {numPages ?? '–'}</span>
      </div>
      <ToolButton label="Next page" onClick={() => controls.goTo(page + 1)} disabled={!numPages || page >= numPages}><ChevronDown aria-hidden="true" /></ToolButton>
      <Separator orientation="vertical" className="mx-1 h-4 data-vertical:self-center" />
      <ToolButton label="Zoom out" onClick={controls.zoomOut} disabled={!controls.canZoomOut}><ZoomOut aria-hidden="true" /></ToolButton>
      <ToolButton label="Zoom in" onClick={controls.zoomIn} disabled={!controls.canZoomIn}><ZoomIn aria-hidden="true" /></ToolButton>
      <ToolButton label="Fit width" onClick={controls.fitWidth}><MoveHorizontal aria-hidden="true" /></ToolButton>
      </div>
      <div className="flex justify-end"><PdfMenu documentId={documentId} pages={numPages} managed={managed} /></div>
    </div>
  )
}
