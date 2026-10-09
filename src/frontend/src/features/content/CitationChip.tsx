import { useRef, useState, useSyncExternalStore, type ReactElement } from 'react'
import { ExternalLinkIcon } from 'lucide-react'
import { downloadUrl } from '@/api/client'
import type { Citation } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCitationSource } from '@/hooks/queries/documents'
import { markdownToText } from '@/lib/markdown-text'
import { cn } from '@/lib/utils'
import { Markdown } from './Markdown'
import { pageLabel, pageSpan, sourceName, spansPages } from './pages'

export type CitationChipProps = {
  citation: Citation
  /** The text this chip supports, handed to onSelect so the reader can mark just the sentences behind it. */
  claim?: string
  onSelect?: (citation: Citation, claim?: string) => void
  className?: string
}

/** After a click or tap, or the focus a closing dialog hands back, no preview opens for this long. */
const previewPause = 600

// Touch-only devices get no hover preview: a tap reads the source directly.
const touchOnlyQuery = '(hover: none)'
function subscribeTouchOnly(onChange: () => void) {
  const media = window.matchMedia(touchOnlyQuery)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}
const useTouchOnly = () => useSyncExternalStore(subscribeTouchOnly, () => window.matchMedia(touchOnlyQuery).matches, () => false)

/**
 * A page chip for one cited passage. Hovering or focusing it previews the passage; activating it hands the
 * citation and its claim to onSelect (the workspace jumps the PDF there) or, without onSelect, opens the passage in
 * a dialog.
 */
export function CitationChip({ citation, claim, onSelect, className }: CitationChipProps) {
  const [preview, setPreview] = useState(false)
  const [reading, setReading] = useState(false)
  const touchOnly = useTouchOnly()
  const pausedUntil = useRef(0)
  const pause = () => { pausedUntil.current = performance.now() + previewPause }
  const source = useCitationSource(citation, preview || reading)

  // One button carries up to two triggers: the preview and, without onSelect, the dialog, which also
  // returns focus here when it closes.
  let chip: ReactElement = (
    <button
      type="button"
      aria-label={sourceName(citation)}
      className={cn(
        'inline-flex h-5 min-w-5 cursor-pointer items-center justify-center rounded-sm bg-muted px-1.5 text-xs leading-none font-medium whitespace-nowrap text-foreground/70 tabular transition-colors outline-none select-none',
        'hover:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_10%)] hover:text-foreground data-[state=open]:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_10%)] data-[state=open]:text-foreground',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        className,
      )}
      onClick={() => {
        pause()
        setPreview(false)
        onSelect?.(citation, claim)
      }}
    >
      {pageLabel(citation)}
    </button>
  )
  if (!touchOnly) chip = <HoverCardTrigger asChild>{chip}</HoverCardTrigger>
  if (!onSelect) chip = <DialogTrigger asChild>{chip}</DialogTrigger>
  if (!touchOnly) {
    chip = (
      <HoverCard openDelay={200} closeDelay={100} open={preview} onOpenChange={(open) => setPreview(open && performance.now() >= pausedUntil.current)}>
        {chip}
        <HoverCardContent side="top" collisionPadding={12} className="grid w-80 max-w-[calc(100vw-1.5rem)] gap-1.5 p-3">
          <p className="flex gap-1.5 text-xs font-medium text-muted-foreground tabular">
            <span>{spansPages(citation) ? 'Pages' : 'Page'} {pageSpan(citation)}</span>
            {citation.kind === 'table' && <><span aria-hidden="true">·</span><span>Table</span></>}
          </p>
          {citation.section && <p className="line-clamp-2 text-xs font-medium text-popover-foreground">{citation.section}</p>}
          <SourcePassage source={source} preview />
        </HoverCardContent>
      </HoverCard>
    )
  }
  if (onSelect) return chip
  return (
    <Dialog open={reading} onOpenChange={setReading}>
      {chip}
      <DialogContent className="sm:max-w-lg" onCloseAutoFocus={pause}>
        <DialogHeader>
          <DialogTitle>Source on {spansPages(citation) ? 'pages' : 'page'} {pageSpan(citation)}</DialogTitle>
          <DialogDescription>Compare this passage with the claim it supports.</DialogDescription>
        </DialogHeader>
        <SourcePassage source={source} />
        <DialogFooter>
          <Button asChild variant="outline">
            <a href={downloadUrl(citation.document_id, citation.page)} target="_blank" rel="noreferrer">
              <ExternalLinkIcon />
              Open PDF at page {citation.page}
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SourcePassage({ source, preview = false }: { source: ReturnType<typeof useCitationSource>; preview?: boolean }) {
  if (source.isError) {
    return (
      <div role="alert" className="grid justify-items-start gap-2 text-sm text-destructive">
        <p>{source.error.message}</p>
        {!preview && <Button size="sm" variant="outline" onClick={() => void source.refetch()}>Try again</Button>}
      </div>
    )
  }
  if (!source.data) {
    return (
      <div role="status" className="grid gap-2 py-1">
        <span className="sr-only">Loading the cited passage…</span>
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-[92%]" />
        <Skeleton className="h-3 w-3/5" />
      </div>
    )
  }
  // Passages are layout Markdown: the clamped preview reads as text, the dialog renders headings and tables.
  if (preview) return <p className="line-clamp-8 text-[13px] leading-relaxed text-popover-foreground">{markdownToText(source.data.excerpt)}</p>
  return (
    <blockquote tabIndex={0} aria-label={`Passage on page ${source.data.page}`} className="max-h-[min(55vh,26rem)] overflow-y-auto rounded-lg bg-muted/60 px-3.5 py-3">
      <Markdown content={source.data.excerpt} className="text-sm leading-relaxed" />
    </blockquote>
  )
}
