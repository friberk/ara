import { useCallback, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { FileQuestion, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useDefaultLayout, usePanelRef } from 'react-resizable-panels'
import { ApiError } from '@/api/client'
import type { Citation, Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { ShellHeader } from '@/components/shell/shell-header'
import { ConversationPane } from '@/features/chat'
import { usePaper } from '@/hooks/queries/papers'
import { useIsMobile } from '@/hooks/use-mobile'
import { DetailsPanel } from './DetailsPanel'
import { MobilePdfView, ReaderPanel } from './ReaderPanel'
import { WorkspaceContext, type HighlightOutcome, type SourceRequest, type WorkspaceContextValue, type WorkspaceView } from './workspace-context'

const views: WorkspaceView[] = ['chat', 'pdf', 'details']
const parseView = (value: string | null): WorkspaceView => views.find((view) => view === value) ?? 'chat'

function PaperTitle({ paper }: { paper: Paper }) {
  return (
    <>
      <h1 className="min-w-0 truncate text-sm font-medium md:text-base">{paper.title || 'Untitled paper'}</h1>
      <DocumentStatusBadge state={paper.document_status} className="shrink-0" />
    </>
  )
}

/** Reader and conversation for one paper; owns the workspace contract the conversation pane talks to. */
function Workspace({ paper, chatId }: { paper: Paper; chatId?: string }) {
  const isMobile = useIsMobile()
  const [searchParams, setSearchParams] = useSearchParams()
  const view = parseView(searchParams.get('view'))
  const [readerTab, setReaderTab] = useState<'pdf' | 'details'>('pdf')
  const [sourceRequest, setSourceRequest] = useState<SourceRequest | null>(null)
  const [highlightOutcome, setHighlightOutcome] = useState<HighlightOutcome | null>(null)
  // A citation from an earlier upload shows that PDF until the reader goes back to the current one.
  const [earlierDocumentId, setEarlierDocumentId] = useState<string | null>(null)
  const [readerCollapsed, setReaderCollapsed] = useState(false)
  const readerPanel = usePanelRef()
  const layout = useDefaultLayout({ id: 'paper-workspace', panelIds: ['reader', 'conversation'] })

  const setView = useCallback((next: WorkspaceView) => {
    setSearchParams((current) => {
      const params = new URLSearchParams(current)
      if (next === 'chat') params.delete('view')
      else params.set('view', next)
      return params
    }, { replace: true })
  }, [setSearchParams])

  const showSource = useCallback((citation: Citation) => {
    setSourceRequest((previous) => ({ citation, nonce: (previous?.nonce ?? 0) + 1 }))
    setHighlightOutcome(null)
    setEarlierDocumentId(citation.document_id === paper.active_document_id ? null : citation.document_id)
    setReaderTab('pdf')
    if (isMobile) setView('pdf')
    else if (readerPanel.current?.isCollapsed()) readerPanel.current.expand()
  }, [isMobile, paper.active_document_id, readerPanel, setView])

  const context = useMemo<WorkspaceContextValue>(() => ({
    paper, view, setView, readerTab, setReaderTab, sourceRequest, showSource, highlightOutcome, reportHighlight: setHighlightOutcome,
  }), [paper, view, setView, readerTab, sourceRequest, showSource, highlightOutcome])

  const documentId = earlierDocumentId ?? (paper.document_status === 'ready' ? paper.active_document_id : null)
  const showCurrent = () => setEarlierDocumentId(null)
  const conversation = <ConversationPane paper={paper} chatId={chatId} />

  return (
    <WorkspaceContext.Provider value={context}>
      <ShellHeader>
        <PaperTitle paper={paper} />
        {!isMobile && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="ml-auto text-muted-foreground" aria-label={readerCollapsed ? 'Show reader' : 'Hide reader'} onClick={() => (readerCollapsed ? readerPanel.current?.expand() : readerPanel.current?.collapse())}>
                {readerCollapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">{readerCollapsed ? 'Show reader' : 'Hide reader'}</TooltipContent>
          </Tooltip>
        )}
      </ShellHeader>
      {isMobile ? (
        <Tabs value={view} onValueChange={(value) => setView(parseView(value))} className="min-h-0 flex-1 gap-0 border-t">
          <div className="px-3 py-2">
            <TabsList className="w-full">
              <TabsTrigger value="chat">Chat</TabsTrigger>
              <TabsTrigger value="pdf">PDF</TabsTrigger>
              <TabsTrigger value="details">Details</TabsTrigger>
            </TabsList>
          </div>
          {/* All three stay mounted so a streaming answer or the reading position survives switching tabs. */}
          <TabsContent value="chat" forceMount hidden={view !== 'chat'} tabIndex={-1} className="flex min-h-0 flex-col">{conversation}</TabsContent>
          <TabsContent value="pdf" forceMount hidden={view !== 'pdf'} tabIndex={-1} className="min-h-0 border-t">
            <MobilePdfView paper={paper} documentId={documentId} onShowCurrent={showCurrent} />
          </TabsContent>
          <TabsContent value="details" forceMount hidden={view !== 'details'} className="min-h-0 border-t"><DetailsPanel paper={paper} onOpenPdf={() => setView('pdf')} /></TabsContent>
        </Tabs>
      ) : (
        <ResizablePanelGroup id="paper-workspace" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1 border-t">
          <ResizablePanel id="reader" panelRef={readerPanel} defaultSize="50%" minSize="30%" collapsible collapsedSize="0%" onResize={(size) => setReaderCollapsed(size.asPercentage < 0.5)}>
            <ReaderPanel paper={paper} documentId={documentId} onShowCurrent={showCurrent} />
          </ResizablePanel>
          <ResizableHandle withHandle className="data-[separator=active]:bg-ring data-[separator=hover]:bg-ring/60" />
          <ResizablePanel id="conversation" minSize="35%">
            <div className="flex h-full min-h-0 flex-col overflow-y-auto">{conversation}</div>
          </ResizablePanel>
        </ResizablePanelGroup>
      )}
    </WorkspaceContext.Provider>
  )
}

function WorkspaceSkeleton() {
  return (
    <div role="status" aria-label="Loading paper" className="flex min-h-0 flex-1 border-t">
      <ShellHeader><Skeleton className="h-4 w-56 max-w-full" /></ShellHeader>
      <div className="hidden w-1/2 border-r bg-muted p-4 md:block"><Skeleton className="mx-auto aspect-[8.5/11] w-full max-w-3xl bg-card" /></div>
      <div className="flex flex-1 flex-col gap-3 p-6">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  )
}

/** /papers/:paperId and /papers/:paperId/chats/:chatId. */
export default function PaperWorkspacePage() {
  const { paperId, chatId } = useParams()
  const query = usePaper(paperId)
  if (query.data) return <Workspace key={query.data.id} paper={query.data} chatId={chatId} />
  if (query.error instanceof ApiError && query.error.status === 404) {
    return <EmptyState icon={FileQuestion} title="Paper not found" action={<Button asChild><Link to="/library">Open library</Link></Button>}>This paper isn’t in your library. It may have been removed.</EmptyState>
  }
  if (query.error) return <div className="mx-auto w-full max-w-3xl p-6"><ErrorNotice error={query.error} retry={() => void query.refetch()} /></div>
  return <WorkspaceSkeleton />
}
