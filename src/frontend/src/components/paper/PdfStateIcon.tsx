import { FileQuestion, FileText, FileWarning, LoaderCircle } from 'lucide-react'
import type { DocumentState } from '@/api/types'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const states = {
  ready: { Icon: FileText, label: 'PDF attached', tone: 'text-foreground' },
  metadata_only: { Icon: FileQuestion, label: 'No PDF yet', tone: 'text-muted-foreground' },
  processing: { Icon: LoaderCircle, label: 'Preparing PDF…', tone: 'text-muted-foreground motion-safe:animate-spin' },
  failed: { Icon: FileWarning, label: 'PDF couldn’t be read', tone: 'text-destructive' },
} as const

/** The tooltip and screen-reader text for a PDF state; the picker reuses it to explain a blocked row. */
export const pdfStateLabel = (state: DocumentState) => states[state].label

/**
 * Whether a paper has a readable PDF, as the leading icon of every paper row: a file in ink when attached, a question
 * mark when none, a spinner while preparing and a warning in red when it failed. Only ink, muted and destructive are used.
 * Hover and keyboard focus open the tooltip; the same text names the icon for screen readers. Pass focusable={false}
 * inside a link or option, which is already the tab stop, and the icon then only opens its tooltip on hover.
 */
export function PdfStateIcon({ state, focusable = true, className }: { state: DocumentState; focusable?: boolean; className?: string }) {
  const { Icon, label, tone } = states[state]
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span role="img" aria-label={label} tabIndex={focusable ? 0 : undefined} className={cn('inline-flex size-4 shrink-0 items-center justify-center rounded-sm', className)}>
          <Icon aria-hidden="true" className={cn('size-4', tone)} />
        </span>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
