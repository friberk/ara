import { useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { usePaper } from '@/hooks/queries/papers'
import { namedPaper, shortPaperName } from '@/lib/paper-names'
import { usePdfControls } from './pdf-controls'
import { PagesSkeleton } from './PagesSkeleton'
import { PdfReader } from './PdfReader'
import { PdfToolbar } from './PdfToolbar'

/**
 * A PDF open in the reader (ARA-088): the workspace's own paper, or another paper a citation asked for. Without a
 * `documentId` the tab shows the paper's current PDF; with one, the version that was cited.
 */
export type ReaderTab = { paperId: string; documentId?: string }

type ReaderDocumentsProps = {
  paper: Paper
  tabs: ReaderTab[]
  active: string
  onActivate: (paperId: string) => void
  onClose: (paperId: string) => void
  onShowCurrent: (paperId: string) => void
}

function useTabPaper(workspace: Paper, paperId: string) {
  const other = usePaper(paperId === workspace.id ? undefined : paperId)
  return paperId === workspace.id ? workspace : other.data
}

function TabEntry({ workspace, tab, closable, onClose }: { workspace: Paper; tab: ReaderTab; closable: boolean; onClose: () => void }) {
  const paper = useTabPaper(workspace, tab.paperId)
  const name = paper ? shortPaperName(namedPaper(paper)) : 'Loading…'
  return (
    <div className="flex shrink-0 items-center">
      <TabsTrigger value={tab.paperId} title={paper?.title ?? undefined} className="h-7 max-w-[12rem] px-2.5 data-[state=active]:bg-muted data-[state=active]:shadow-none"><span className="truncate">{name}</span></TabsTrigger>
      {closable && (
        <Button type="button" variant="ghost" size="icon-xs" className="-ml-1 text-muted-foreground hover:text-foreground" aria-label={`Close ${name}`} onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      )}
    </div>
  )
}

function ReaderDocument({ workspace, tab, active, toolbarSlot, onShowCurrent }: { workspace: Paper; tab: ReaderTab; active: boolean; toolbarSlot: HTMLElement | null; onShowCurrent: () => void }) {
  const paper = useTabPaper(workspace, tab.paperId)
  const documentId = tab.documentId ?? (paper?.document_status === 'ready' ? paper.active_document_id : null)
  const controls = usePdfControls(documentId)
  return (
    <div hidden={!active} className="h-full min-h-0">
      {paper ? <PdfReader paper={paper} documentId={documentId} controls={controls} onShowCurrent={onShowCurrent} /> : <PagesSkeleton />}
      {/* Only the workspace paper's current PDF can be replaced or removed here; other PDFs open or download. */}
      {active && documentId && toolbarSlot && createPortal(<PdfToolbar controls={controls} documentId={documentId} managed={paper?.id === workspace.id && documentId === paper.active_document_id ? paper : undefined} />, toolbarSlot)}
    </div>
  )
}

/**
 * The reader's open PDFs. Each keeps its reading position while another is shown; a tab strip appears once a second
 * paper is open (or the workspace's own one was closed), and any tab but the last can be closed.
 */
export function ReaderDocuments({ paper, tabs, active, onActivate, onClose, onShowCurrent }: ReaderDocumentsProps) {
  const [toolbarSlot, setToolbarSlot] = useState<HTMLDivElement | null>(null)
  const strip = tabs.length > 1 || tabs[0]?.paperId !== paper.id
  const current = tabs.some((tab) => tab.paperId === active) ? active : tabs[0]?.paperId
  return (
    <div className="flex h-full min-h-0 flex-col">
      {strip && (
        <Tabs value={current} onValueChange={onActivate} className="shrink-0 border-b px-2 py-1">
          {/* Any number of papers can be open: the strip scrolls sideways instead of wrapping. */}
          <TabsList aria-label="Open PDFs" className="h-auto w-full max-w-full justify-start overflow-x-auto overflow-y-hidden bg-transparent p-0 [scrollbar-width:thin]">
            {tabs.map((tab) => <TabEntry key={tab.paperId} workspace={paper} tab={tab} closable={tabs.length > 1} onClose={() => onClose(tab.paperId)} />)}
          </TabsList>
        </Tabs>
      )}
      {/* The active PDF's controls; empty, and so hidden, while the reader shows a way to get the PDF. */}
      <div ref={setToolbarSlot} className="flex min-h-11 shrink-0 items-center border-b px-2 py-1.5 empty:hidden" />
      <div className="min-h-0 flex-1">
        {tabs.map((tab) => (
          <ReaderDocument key={tab.paperId} workspace={paper} tab={tab} active={tab.paperId === current} toolbarSlot={toolbarSlot} onShowCurrent={() => onShowCurrent(tab.paperId)} />
        ))}
      </div>
    </div>
  )
}
