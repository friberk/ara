import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import type { Paper, UploadAccepted } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { JobProgress } from '@/components/jobs/JobProgress'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
import { useJobs, useRetryJob } from '@/hooks/queries/jobs'
import { queryKeys } from '@/lib/query-keys'

function Abstract({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <section className="grid gap-2">
      <h2 className="text-sm font-medium">Abstract</h2>
      <p className="text-sm leading-relaxed whitespace-pre-line text-pretty text-muted-foreground">{text}</p>
    </section>
  )
}

/** Ingest jobs for this paper only; the paper filter is checked here too in case the server ignores it. */
function useIngestJob(paper: Paper, active: boolean, enabled = true) {
  const jobs = useJobs({ paperId: paper.id, kind: 'ingest', active: active || null }, { enabled })
  return jobs.data?.items.find((job) => job.kind === 'ingest' && job.paper_id === paper.id && (active ? job.state !== 'failed' : job.state === 'failed'))
}

/** Follows an ingest job: the one just uploaded here, else the paper's active job when the server can say which. */
function ProcessingGate({ paper, jobId, onSettled }: { paper: Paper; jobId?: string; onSettled?: (failed: boolean) => void }) {
  const client = useQueryClient()
  const active = useIngestJob(paper, true, !jobId)
  const followed = jobId ?? active?.id
  return (
    <div className="grid gap-6">
      <div className="grid gap-1.5">
        <h2 className="flex items-center gap-2 text-sm font-medium"><Spinner aria-hidden="true" />{jobId ? 'PDF uploaded. Processing continues in the background.' : 'Processing the PDF'}</h2>
        <p className="text-sm text-muted-foreground">Reading its pages and bibliography. The reader opens here when it’s ready.</p>
      </div>
      {followed && <JobProgress jobId={followed} label="PDF processing progress" onSettled={(job) => { void client.invalidateQueries({ queryKey: queryKeys.papers.detail(paper.id) }); onSettled?.(job.state === 'failed') }} />}
      <Skeleton className="aspect-[8.5/11] w-full" />
    </div>
  )
}

function FailedGate({ paper, onAccepted }: { paper: Paper; onAccepted: (accepted: UploadAccepted) => void }) {
  const job = useIngestJob(paper, false)
  const retry = useRetryJob()
  return (
    <div className="grid gap-6">
      <div className="grid gap-1.5">
        <h2 className="text-sm font-medium">This PDF couldn’t be processed</h2>
        <p className="text-sm text-muted-foreground">{job?.error?.message ?? 'Text-based PDFs work best. Scanned pages need text recognition, which is turned off.'}</p>
      </div>
      {job && (
        <div className="grid justify-items-start gap-3">
          <Button variant="outline" size="sm" disabled={retry.isPending} onClick={() => retry.mutate(job.id)}><RotateCcw data-icon="inline-start" aria-hidden="true" />{retry.isPending ? 'Retrying…' : 'Retry processing'}</Button>
          <ErrorNotice error={retry.error} />
        </div>
      )}
      <UploadDropzone paperId={paper.id} title="Upload a different PDF" onAccepted={onAccepted} />
    </div>
  )
}

/** What the reader shows until the paper has a readable PDF: attach it, wait for processing, or recover. */
export function ReaderGate({ paper }: { paper: Paper }) {
  // An upload started here is followed here, even before the paper itself reports that it is processing.
  const [uploaded, setUploaded] = useState<UploadAccepted | null>(null)
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid max-w-md gap-8 px-5 py-10">
        {uploaded ? <ProcessingGate paper={paper} jobId={uploaded.job_id} onSettled={(failed) => { if (failed) setUploaded(null) }} />
          : paper.document_status === 'processing' ? <ProcessingGate paper={paper} />
          : paper.document_status === 'failed' ? <FailedGate paper={paper} onAccepted={setUploaded} />
          : <UploadDropzone paperId={paper.id} title="Attach the PDF to read, summarize and ask" description="Text-based PDF, up to 25 MB. The reader, summaries and answers all cite its pages." onAccepted={setUploaded} />}
        <Abstract text={paper.document_status === 'metadata_only' && !uploaded ? paper.abstract : null} />
      </div>
    </div>
  )
}
