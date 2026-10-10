import { useState } from 'react'
import type { Paper } from '@/api/types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DetailsPanel } from './DetailsPanel'
import { ReaderDocuments, type ReaderTab } from './ReaderDocuments'
import { useWorkspace } from './workspace-context'

type ReaderProps = {
  paper: Paper
  tabs: ReaderTab[]
  active: string
  onActivate: (paperId: string) => void
  onClose: (paperId: string) => void
  onShowCurrent: (paperId: string) => void
}

/**
 * Desktop reader: PDF and Details tabs with the PDF controls on the same bar. Both tabs stay mounted, so
 * switching to Details and back keeps the reading position; so do the open PDFs of a chat's other papers.
 */
export function ReaderPanel({ paper, ...documents }: ReaderProps) {
  const { readerTab, setReaderTab } = useWorkspace()
  const [toolbar, setToolbar] = useState<HTMLDivElement | null>(null)
  return (
    <Tabs value={readerTab} onValueChange={(value) => setReaderTab(value === 'details' ? 'details' : 'pdf')} className="h-full min-h-0 gap-0">
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-2 py-1.5">
        <TabsList>
          <TabsTrigger value="pdf" className="px-3">PDF</TabsTrigger>
          <TabsTrigger value="details" className="px-3">Details</TabsTrigger>
        </TabsList>
        <div ref={setToolbar} hidden={readerTab !== 'pdf'} className="flex items-center" />
      </div>
      <TabsContent value="pdf" forceMount hidden={readerTab !== 'pdf'} tabIndex={-1} className="min-h-0">
        <ReaderDocuments paper={paper} toolbarSlot={toolbar} {...documents} />
      </TabsContent>
      <TabsContent value="details" forceMount hidden={readerTab !== 'details'} className="min-h-0">
        <DetailsPanel paper={paper} onOpenPdf={() => setReaderTab('pdf')} />
      </TabsContent>
    </Tabs>
  )
}

/** Narrow screens: the PDF view of the Chat/PDF/Details tabs, with its own controls bar. */
export function MobilePdfView({ paper, ...documents }: ReaderProps) {
  return <ReaderDocuments paper={paper} {...documents} />
}
