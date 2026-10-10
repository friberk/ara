import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FileUp, RefreshCw } from 'lucide-react'
import type { Citation, Job, Paper } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { JobProgress } from '@/components/jobs/JobProgress'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
import { Markdown, SourceList } from '@/features/content'
import { useOptionalWorkspace } from '@/features/workspace/workspace-context'
import { useFullText } from '@/hooks/queries/fulltext'
import { useJobs } from '@/hooks/queries/jobs'
import { useGenerateSummary, useSummaries } from '@/hooks/queries/summaries'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

/** Why a summary cannot be generated right now, or null when it can. */
function summaryGate(paper: Paper, usable: boolean, loadingModels: boolean) {
  if (paper.document_status === 'processing') return 'The summary starts automatically when the PDF is ready.'
  if (paper.document_status === 'failed') return 'PDF processing failed. Attach a text-based PDF to generate a summary.'
  if (paper.document_status !== 'ready' || !paper.active_document_id) return 'Attach a PDF to generate a summary.'
  if (!loadingModels && !usable) return 'The selected model can’t write summaries. Choose another model in the composer.'
  return null
}
const unsettled = (job: Pick<Job, 'state'>) => job.state !== 'completed' && job.state !== 'failed'

/**
 * The paper summary as the first message of every conversation: the latest version, and live progress for a
 * summary job, including one started before a reload.
 */
export function SummaryCard({ paper, className }: { paper: Paper; className?: string }) {
  const client = useQueryClient()
  const workspace = useOptionalWorkspace()
  const generation = useGenerationSettings()
  const summaries = useSummaries(paper.id)
  const generate = useGenerateSummary(paper.id)
  const jobs = useJobs({ paperId: paper.id, kind: 'summary', active: true })
  // While the PDF is still being retrieved, the summary waits for it instead of asking for an upload.
  const fulltext = useFullText(paper.document_status === 'metadata_only' ? paper.id : undefined)
  const retrieving = ['queued', 'processing'].includes(fulltext.data?.retrieval_job?.state ?? '')
  const [finishedJobs, setFinishedJobs] = useState<string[]>([])
  const [failure, setFailure] = useState<Error | null>(null)
  const [open, setOpen] = useState(false)
  const contentId = useId()

  const current = [...(summaries.data?.items ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at)).at(-1)
  const summarized = current?.document_id
  const documents = useMemo(() => new Set(summarized ? [summarized] : []), [summarized])
  // Another paper's summary (shown from a chat's paper chip) names its paper, so the reader opens that paper's tab.
  const showSource = !workspace ? undefined : !workspace.paper || workspace.paper.id === paper.id ? workspace.showSource : (citation: Citation, claim?: string) => workspace.showSource({ ...citation, paper_id: paper.id }, claim)
  // The job this card started, else one still running from before a reload. The list is filtered again here
  // because a server without the job filters answers with every job.
  const running = (jobs.data?.items ?? []).filter((job) => job.kind === 'summary' && job.paper_id === paper.id && unsettled(job)).map((job) => job.id)
  const activeJob = [generate.data?.job_id, ...running].find((id): id is string => !!id && !finishedJobs.includes(id))
  const gate = summaryGate(paper, generation.usableFor('summary'), generation.loading)
  const canGenerate = !gate && !generation.loading && !activeJob && !generate.isPending
  // Without a usable PDF the next step is attaching one, not a disabled Generate summary.
  const needsPdf = (paper.document_status === 'metadata_only' && !retrieving) || paper.document_status === 'failed'
  // Why the server will not, or did not, summarize this PDF by itself with the saved default.
  const blocked = summaries.data?.blocked
  const waiting = paper.document_status === 'processing' || (paper.document_status === 'metadata_only' && retrieving)
  const note = waiting ? (blocked ? `The summary won’t start by itself. ${blocked.message}` : paper.document_status === 'processing' ? gate : 'The summary starts when the PDF is ready.')
    : paper.document_status === 'ready' && blocked ? `Not summarized automatically. ${blocked.message}` : gate

  // A PDF that has just become ready may already have its automatic summary job queued.
  const readyDocument = paper.document_status === 'ready' ? paper.active_document_id : null
  const seenReady = useRef(readyDocument)
  const { refetch: refetchJobs } = jobs
  const { refetch: refetchSummaries } = summaries
  useEffect(() => {
    if (readyDocument && readyDocument !== seenReady.current) { void refetchJobs(); void refetchSummaries() }
    seenReady.current = readyDocument
  }, [readyDocument, refetchJobs, refetchSummaries])

  function start() {
    if (!canGenerate) return
    setFailure(null)
    generate.mutate(generation.settings)
  }
  function settle(job: Job) {
    setFinishedJobs((ids) => [...ids, job.id])
    generate.reset()
    void client.invalidateQueries({ queryKey: queryKeys.summaries(paper.id) })
    void client.invalidateQueries({ queryKey: queryKeys.jobs.all })
    if (job.state === 'failed') setFailure(new Error(job.error?.message ? `The summary could not be generated. ${job.error.message}` : 'The summary could not be generated. Try again.'))
    else setOpen(true)
  }

  return (
    <article aria-label="Paper summary" className={cn('rounded-2xl bg-muted/60 px-4 py-3.5 sm:px-5', className)}>
      <div className="flex min-h-7 flex-wrap items-center gap-x-2 gap-y-1">
        <h2 className="text-sm font-semibold">Summary</h2>
        {current && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="button" variant="ghost" size="icon-xs" className="text-muted-foreground hover:text-foreground" aria-label="Regenerate summary" disabled={!canGenerate} onClick={start}>
                <RefreshCw aria-hidden="true" className={cn((activeJob || generate.isPending) && 'animate-spin motion-reduce:animate-none')} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Regenerate summary</TooltipContent>
          </Tooltip>
        )}
        {current && current.document_id !== paper.active_document_id && <Badge variant="outline" className="font-normal text-muted-foreground">Earlier PDF</Badge>}
      </div>
      {activeJob && <JobProgress jobId={activeJob} onSettled={settle} label="Summary progress" className="mt-3" />}
      <ErrorNotice error={generate.error ?? failure} retry={canGenerate ? start : undefined} className="mt-3" />
      <ErrorNotice error={summaries.error} retry={() => void summaries.refetch()} className="mt-3" />

      {summaries.isPending && (
        <div className="mt-3 grid gap-2" role="status" aria-label="Loading summary">
          <Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/4" />
        </div>
      )}

      {current ? (
        <>
          <div
            id={contentId}
            inert={!open}
            className={cn('mt-3 grid gap-3 text-[15.5px] leading-7', !open && 'max-h-44 overflow-hidden mask-b-from-50%')}
          >
            <Markdown content={current.content} citations={current.citations} documents={documents} onCitation={showSource} />
            <SourceList citations={current.citations} documents={documents} context={current.content} onSelect={showSource} className="flex flex-wrap gap-1.5" />
          </div>
          <Button type="button" variant="ghost" size="sm" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(!open)} className="mt-1 -ml-2 text-muted-foreground hover:text-foreground">
            {open ? 'Collapse summary' : 'Show full summary'}
            <ChevronDown aria-hidden="true" className={cn('transition-transform', open && 'rotate-180')} />
          </Button>
        </>
      ) : summaries.isSuccess && !activeJob && (
        <div className="mt-1.5 grid justify-items-start gap-3">
          <p className="text-sm text-muted-foreground">{note ?? 'A structured summary of the whole paper, with page sources you can check.'}</p>
          {needsPdf ? (
            <AttachPdf paperId={paper.id} />
          ) : paper.document_status === 'ready' && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Button type="button" size="sm" disabled={!canGenerate} onClick={start}>
                {generate.isPending && <Spinner data-icon="inline-start" aria-hidden="true" />}
                Generate summary
              </Button>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

/** Opens the upload for this paper; the workspace refreshes into processing when it is accepted. */
function AttachPdf({ paperId }: { paperId: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button type="button" size="sm" onClick={() => setOpen(true)}><FileUp data-icon="inline-start" aria-hidden="true" />Attach PDF</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Attach the PDF</DialogTitle>
            <DialogDescription>Summaries and answers read this PDF and cite its pages.</DialogDescription>
          </DialogHeader>
          <UploadDropzone paperId={paperId} onAccepted={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </>
  )
}
