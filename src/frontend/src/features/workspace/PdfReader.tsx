import { Component, lazy, Suspense } from 'react'
import { History } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useDocument } from '@/hooks/queries/documents'
import type { PdfControls } from './pdf-controls'
import { PagesSkeleton } from './PagesSkeleton'
import { PaperHeader, PdfHeading } from './PaperHeader'
import { PdfToolbar } from './PdfToolbar'
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

/**
 * The PDF's bar: its heading and file name on the left, its controls on the right. It sits between the paper header
 * and page 1 and docks at the top of the reader once the header has scrolled away, so the controls stay with the PDF.
 */
function PdfBar({ fileName, controls, documentId, managed }: { fileName?: string | null; controls: PdfControls; documentId: string; managed?: Paper }) {
  return (
    <div className="@container flex min-h-11 items-center gap-3 py-1.5">
      <PdfHeading fileName={fileName} className="flex-1" />
      <PdfToolbar controls={controls} documentId={documentId} managed={managed} className="-mr-2 shrink-0" />
    </div>
  )
}

/**
 * The PDF tab: a gate until the paper has a readable PDF, then the viewer. documentId is the version on screen,
 * which is the active PDF unless a citation asked for an earlier one. `managed` is the workspace paper when this is
 * its current PDF, which the PDF menu can then replace or remove.
 */
export function PdfReader({ paper, documentId, controls, managed, onShowCurrent }: { paper: Paper; documentId: string | null; controls: PdfControls; managed?: Paper; onShowCurrent: () => void }) {
  const { sourceRequest, highlightOutcome, reportHighlight } = useWorkspace()
  // The PDF menu reads the same record, so naming an earlier version costs no second request.
  const file = useDocument(documentId)
  if (!documentId) return <ReaderGate paper={paper} />
  const highlight = sourceRequest?.citation.document_id === documentId ? sourceRequest : null
  const outcome = highlight ? highlightOutcome : null
  const current = documentId === paper.active_document_id
  // Above page 1: the paper header, which scrolls away, then the PDF's bar, which docks. An earlier version's bar
  // names that version's file under the banner that says it is earlier.
  const header = <PaperHeader paper={paper} />
  const bar = <PdfBar fileName={current ? paper.file_name : file.data?.file_name} controls={controls} documentId={documentId} managed={managed} />
  return (
    <div className="flex h-full min-h-0 flex-col">
      {!current && (
        <div className="flex items-center gap-3 border-b bg-muted/50 px-4 py-2 text-sm">
          <History className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <p className="min-w-0 flex-1">Showing an earlier PDF version</p>
          {/* After Remove PDF a chat's kept PDF has no current one to go back to, so the way out is adding one (ARA-097). */}
          <Button size="xs" variant="outline" onClick={onShowCurrent}>{paper.active_document_id ? 'Back to current PDF' : 'Add a new PDF'}</Button>
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
          {/* Until pdf.js has loaded, the header and the bar already show above page-shaped placeholders. */}
          <Suspense fallback={<div className="h-full overflow-hidden bg-background"><div className="px-4">{header}{bar}</div><PagesSkeleton /></div>}>
            <PdfViewer
              key={documentId}
              documentId={documentId}
              zoom={controls.zoom}
              navigation={controls.navigation}
              highlight={highlight}
              onDocumentLoad={controls.onDocumentLoad}
              onPageChange={controls.onPageChange}
              onHighlight={reportHighlight}
              header={header}
              bar={bar}
            />
          </Suspense>
        </ReaderErrorBoundary>
      </div>
    </div>
  )
}
