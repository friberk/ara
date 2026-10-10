import { FileQuestion, FileText, FileWarning, LoaderCircle } from 'lucide-react'
import type { DocumentState } from '@/api/types'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { pdfStateLabels } from './pdf-state'

const states = {
  ready: { Icon: FileText, tone: 'text-foreground' },
  metadata_only: { Icon: FileQuestion, tone: 'text-muted-foreground' },
  processing: { Icon: LoaderCircle, tone: 'text-muted-foreground motion-safe:animate-spin' },
  failed: { Icon: FileWarning, tone: 'text-destructive' },
} as const

/**
 * Whether a paper has a readable PDF, as the leading icon of every paper row: a file in ink when attached, a question
 * mark when none, a spinner while preparing and a warning in red when it failed. Only ink, muted and destructive are used.
 * Hover and keyboard focus open the tooltip; the same text names the icon for screen readers. Pass focusable={false}
 * inside a link or option, which is already the tab stop, and the icon then only opens its tooltip on hover.
 */
export function PdfStateIcon({ state, focusable = true, className }: { state: DocumentState; focusable?: boolean; className?: string }) {
  const { Icon, tone } = states[state]
  const label = pdfStateLabels[state]
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
