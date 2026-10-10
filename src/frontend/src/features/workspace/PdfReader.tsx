import { Component, lazy, Suspense } from 'react'
import { FileX2, History } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import type { PdfControls } from './pdf-controls'
import { PagesSkeleton } from './PagesSkeleton'
import { ReaderGate } from './ReaderGate'
import { useWorkspace } from './workspace-context'

// pdf.js is large, so it loads only when a PDF is actually shown.
const PdfViewer = lazy(() => import('./PdfViewer'))

class ReaderErrorBoundary extends Component<{ children: React.ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (!this.state.error) return this.props.children
    return <div className="p-4"><ErrorNotice error={new Error('The PDF reader couldn’t load. Reload the page, or open the original PDF.')} retry={() => this.setState({ error: null })} /></div>
  }
}

/** A cited PDF that was removed from its paper (ARA-097): the answer's quoted passage still reads, its page does not. */
export function RemovedPdf({ current, onShowCurrent }: { current: boolean; onShowCurrent: () => void }) {
  return (
    <div className="grid h-full content-center justify-items-center gap-3 px-6 py-10 text-center">
      <FileX2 className="size-5 text-muted-foreground" aria-hidden="true" />
      <div className="grid gap-1">
        <h2 className="text-sm font-medium">This PDF was removed</h2>
        <p className="max-w-xs text-sm text-pretty text-muted-foreground">The answer keeps its quoted passage, but its page can’t open.</p>
      </div>
      <Button size="sm" variant="outline" onClick={onShowCurrent}>{current ? 'Back to current PDF' : 'Add a PDF'}</Button>
    </div>
  )
}

/**
 * The PDF tab: a gate until the paper has a readable PDF, then the viewer. documentId is the version on screen,
 * which is the active PDF unless a citation asked for an earlier one.
 */
export function PdfReader({ paper, documentId, controls, onShowCurrent }: { paper: Paper; documentId: string | null; controls: PdfControls; onShowCurrent: () => void }) {
  const { sourceRequest, highlightOutcome, reportHighlight } = useWorkspace()
  if (!documentId) return <ReaderGate paper={paper} />
  const highlight = sourceRequest?.citation.document_id === documentId ? sourceRequest : null
  const outcome = highlight ? highlightOutcome : null
  return (
    <div className="flex h-full min-h-0 flex-col">
      {documentId !== paper.active_document_id && (
        <div className="flex items-center gap-3 border-b bg-muted/50 px-4 py-2 text-sm">
          <History className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <p className="min-w-0 flex-1">Showing an earlier PDF version</p>
          <Button size="xs" variant="outline" onClick={onShowCurrent}>Back to current PDF</Button>
        </div>
      )}
      {/* One polite announcement per jump; the visible note repeats the region and page-only cases for sighted readers. */}
      <div role="status" aria-live="polite" className="sr-only">
        {outcome === 'highlighted' && highlight && `Highlighted the cited passage on page ${highlight.citation.page}.`}
        {outcome === 'region' && highlight && `Outlined the cited region on page ${highlight.citation.page}.`}
        {outcome === 'page-only' && highlight && `Showing page ${highlight.citation.page}. The cited passage could not be highlighted.`}
      </div>
      {outcome === 'region' && highlight && <p aria-hidden="true" className="border-b px-4 py-2 text-xs text-muted-foreground">Couldn’t find the exact text, so outlined the cited region on page {highlight.citation.page}.</p>}
      {outcome === 'page-only' && highlight && <p aria-hidden="true" className="border-b px-4 py-2 text-xs text-muted-foreground">Couldn’t pinpoint the passage, so showing page {highlight.citation.page}.</p>}
      <div className="min-h-0 flex-1">
        <ReaderErrorBoundary key={documentId}>
          <Suspense fallback={<PagesSkeleton />}>
            <PdfViewer
              key={documentId}
              documentId={documentId}
              zoom={controls.zoom}
              navigation={controls.navigation}
              highlight={highlight}
              onDocumentLoad={controls.onDocumentLoad}
              onPageChange={controls.onPageChange}
              onHighlight={reportHighlight}
            />
          </Suspense>
        </ReaderErrorBoundary>
      </div>
    </div>
  )
}
