import { useCallback, useMemo, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useDefaultLayout, usePanelRef } from 'react-resizable-panels'
import { ApiError } from '@/api/client'
import type { Citation, Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { ShellHeader } from '@/components/shell/shell-header'
import { MatchDecision } from '@/components/upload/MatchDecision'
import { ConversationPane } from '@/features/chat'
import { paperName } from '@/features/research/paper-format'
import { usePaper } from '@/hooks/queries/papers'
import { useIsMobile } from '@/hooks/use-mobile'
import { JoinedRedirect } from './JoinedRedirect'
import { PaperStatusBadge } from './PaperStatusBadge'
import type { ReaderTab } from './ReaderDocuments'
import { PaperDetailsSheet } from './PaperDetailsSheet'
import { ReaderPanel } from './ReaderPanel'
import { WorkspaceContext, type HighlightOutcome, type SourceRequest, type WorkspaceContextValue, type WorkspaceView } from './workspace-context'

// Narrow screens show the conversation or the reader; an old ?view=details link opens the conversation.
const views: WorkspaceView[] = ['chat', 'pdf']
const parseView = (value: string | null): WorkspaceView => views.find((view) => view === value) ?? 'chat'

/** The paper's name and PDF status, with ⓘ for its details beside them (ARA-097). */
function PaperTitle({ paper, onDeleted }: { paper: Paper; onDeleted: () => void }) {
  return (
    <>
      <h1 className="min-w-0 truncate text-sm font-medium md:text-base">{paperName(paper)}</h1>
      <PaperStatusBadge paper={paper} className="shrink-0" />
      <PaperDetailsSheet paper={paper} onDeleted={onDeleted} />
    </>
  )
}

/** Reader and conversation for one paper; owns the workspace contract the conversation pane talks to. */
function Workspace({ paper, chatId }: { paper: Paper; chatId?: string }) {
  const isMobile = useIsMobile()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const view = parseView(searchParams.get('view'))
  const [sourceRequest, setSourceRequest] = useState<SourceRequest | null>(null)
  const [highlightOutcome, setHighlightOutcome] = useState<HighlightOutcome | null>(null)
  // The open PDFs: this paper's (an earlier upload while a citation asks for it) and other papers a chat cites (ARA-088).
  const [readerTabs, setReaderTabs] = useState<ReaderTab[]>([{ paperId: paper.id }])
  const [activeTab, setActiveTab] = useState(paper.id)
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

  const showSource = useCallback((citation: Citation, claim?: string) => {
    setSourceRequest((previous) => ({ citation, claim, nonce: (previous?.nonce ?? 0) + 1 }))
    setHighlightOutcome(null)
    // Another paper's citation opens that paper in its own tab, or focuses the tab it already has.
    const paperId = citation.paper_id ?? paper.id
    const documentId = paperId === paper.id && citation.document_id === paper.active_document_id ? undefined : citation.document_id
    setReaderTabs((current) => current.some((tab) => tab.paperId === paperId) ? current.map((tab) => (tab.paperId === paperId ? { paperId, documentId } : tab)) : [...current, { paperId, documentId }])
    setActiveTab(paperId)
    if (isMobile) setView('pdf')
    else if (readerPanel.current?.isCollapsed()) readerPanel.current.expand()
  }, [isMobile, paper.id, paper.active_document_id, readerPanel, setView])

  const context = useMemo<WorkspaceContextValue>(() => ({
    paper, view, setView, sourceRequest, showSource, highlightOutcome, reportHighlight: setHighlightOutcome,
  }), [paper, view, setView, sourceRequest, showSource, highlightOutcome])

  const documents = {
    tabs: readerTabs,
    active: activeTab,
    onActivate: setActiveTab,
    onClose: (paperId: string) => {
      if (readerTabs.length < 2) return
      const index = readerTabs.findIndex((tab) => tab.paperId === paperId)
      const rest = readerTabs.filter((tab) => tab.paperId !== paperId)
      setReaderTabs(rest)
      if (paperId === activeTab) setActiveTab(rest[Math.min(index, rest.length - 1)]!.paperId)
    },
    // Back to the paper's current PDF from an earlier version a citation opened.
    onShowCurrent: (paperId: string) => setReaderTabs((current) => current.map((tab) => (tab.paperId === paperId ? { paperId } : tab))),
  }
  const conversation = <ConversationPane paper={paper} chatId={chatId} />

  return (
    <WorkspaceContext.Provider value={context}>
      <ShellHeader>
        <PaperTitle paper={paper} onDeleted={() => navigate('/library', { replace: true })} />
        {!isMobile && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="ml-auto shrink-0 text-muted-foreground" aria-label={readerCollapsed ? 'Show reader' : 'Hide reader'} onClick={() => (readerCollapsed ? readerPanel.current?.expand() : readerPanel.current?.collapse())}>
                {readerCollapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">{readerCollapsed ? 'Show reader' : 'Hide reader'}</TooltipContent>
          </Tooltip>
        )}
      </ShellHeader>
      {paper.upload_match && paper.document_status === 'ready' && <MatchDecision paper={{ ...paper, upload_match: paper.upload_match }} variant="banner" />}
      {isMobile ? (
        <Tabs value={view} onValueChange={(value) => setView(parseView(value))} className="min-h-0 flex-1 gap-0 border-t">
          <div className="px-3 py-2">
            <TabsList className="w-full">
              <TabsTrigger value="chat">Chat</TabsTrigger>
              <TabsTrigger value="pdf">PDF</TabsTrigger>
            </TabsList>
          </div>
          {/* Both stay mounted so a streaming answer or the reading position survives switching. */}
          <TabsContent value="chat" forceMount hidden={view !== 'chat'} tabIndex={-1} className="flex min-h-0 flex-col">{conversation}</TabsContent>
          <TabsContent value="pdf" forceMount hidden={view !== 'pdf'} tabIndex={-1} className="min-h-0 border-t">
            <ReaderPanel paper={paper} {...documents} />
          </TabsContent>
        </Tabs>
      ) : (
        <ResizablePanelGroup id="paper-workspace" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1 border-t">
          <ResizablePanel id="reader" panelRef={readerPanel} defaultSize="50%" minSize="30%" collapsible collapsedSize="0%" onResize={(size) => setReaderCollapsed(size.asPercentage < 0.5)}>
            {/* A collapsed reader keeps its state but leaves the tab order and the accessibility tree. */}
            <div className="h-full" inert={readerCollapsed}>
              <ReaderPanel paper={paper} {...documents} />
            </div>
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
  if (query.data && paperId && query.data.id !== paperId) return <JoinedRedirect paper={query.data} />
  if (query.data) return <Workspace key={query.data.id} paper={query.data} chatId={chatId} />
  // A deleted paper's link returns to the Library, which says why (ARA-095).
  if (query.error instanceof ApiError && query.error.status === 404) return <Navigate to="/library" replace state={{ missingPaper: true }} />
  if (query.error) return <div className="mx-auto w-full max-w-3xl p-6"><ErrorNotice error={query.error} retry={() => void query.refetch()} /></div>
  return <WorkspaceSkeleton />
}
