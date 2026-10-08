import type { Paper } from '@/api/types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DetailsPanel } from './DetailsPanel'
import { usePdfControls } from './pdf-controls'
import { PdfReader } from './PdfReader'
import { PdfToolbar } from './PdfToolbar'
import { useWorkspace } from './workspace-context'

type ReaderProps = { paper: Paper; documentId: string | null; onShowCurrent: () => void }

/**
 * Desktop reader: PDF and Details tabs with the PDF controls on the same bar. Both tabs stay mounted, so
 * switching to Details and back keeps the reading position.
 */
export function ReaderPanel({ paper, documentId, onShowCurrent }: ReaderProps) {
  const { readerTab, setReaderTab } = useWorkspace()
  const controls = usePdfControls(documentId)
  return (
    <Tabs value={readerTab} onValueChange={(value) => setReaderTab(value === 'details' ? 'details' : 'pdf')} className="h-full min-h-0 gap-0">
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-2 py-1.5">
        <TabsList>
          <TabsTrigger value="pdf" className="px-3">PDF</TabsTrigger>
          <TabsTrigger value="details" className="px-3">Details</TabsTrigger>
        </TabsList>
        {readerTab === 'pdf' && documentId && <PdfToolbar controls={controls} documentId={documentId} />}
      </div>
      <TabsContent value="pdf" forceMount hidden={readerTab !== 'pdf'} tabIndex={-1} className="min-h-0">
        <PdfReader paper={paper} documentId={documentId} controls={controls} onShowCurrent={onShowCurrent} />
      </TabsContent>
      <TabsContent value="details" forceMount hidden={readerTab !== 'details'} className="min-h-0">
        <DetailsPanel paper={paper} onOpenPdf={() => setReaderTab('pdf')} />
      </TabsContent>
    </Tabs>
  )
}

/** Narrow screens: the PDF view of the Chat/PDF/Details tabs, with its own controls bar. */
export function MobilePdfView({ paper, documentId, onShowCurrent }: ReaderProps) {
  const controls = usePdfControls(documentId)
  return (
    <div className="flex h-full min-h-0 flex-col">
      {documentId && (
        <div className="flex min-h-11 items-center justify-center border-b px-2 py-1.5">
          <PdfToolbar controls={controls} documentId={documentId} />
        </div>
      )}
      <div className="min-h-0 flex-1">
        <PdfReader paper={paper} documentId={documentId} controls={controls} onShowCurrent={onShowCurrent} />
      </div>
    </div>
  )
}
