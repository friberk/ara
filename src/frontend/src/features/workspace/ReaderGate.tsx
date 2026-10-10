import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'
import type { Paper, UploadAccepted } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { MatchDecision } from '@/components/upload/MatchDecision'
import { PreparationSteps } from '@/components/upload/PreparationSteps'
import { usePreparation } from '@/components/upload/use-preparation'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
import { useJobs, useRetryJob } from '@/hooks/queries/jobs'
import { usePdfComing } from '@/hooks/queries/uploads'
import { FullTextAccess } from './FullTextAccess'
import { PaperHeader, PdfHeading } from './PaperHeader'

/** The paper's latest failed ingest job; the paper filter is checked here too in case the server ignores it. */
function useFailedIngest(paper: Paper) {
  const jobs = useJobs({ paperId: paper.id, kind: 'ingest', active: false })
  return jobs.data?.items.find((job) => job.kind === 'ingest' && job.paper_id === paper.id && job.state === 'failed')
}

/**
 * The steps of the PDF being prepared: the ingest job started here when there is one, else the paper's active job.
 * It names no source, because the PDF may have been uploaded or retrieved automatically.
 */
function ProcessingGate({ paper, jobId, uploaded, onSettled }: { paper: Paper; jobId?: string; uploaded?: boolean; onSettled?: (failed: boolean) => void }) {
  const steps = usePreparation({ paperId: paper.id, documentStatus: paper.document_status, jobId, uploaded, onSettled: (job) => onSettled?.(job.state === 'failed') })
  return (
    <div className="grid gap-6">
      <div className="grid gap-1.5">
        <h4 className="text-sm font-medium">Preparing the PDF</h4>
        <p className="text-sm text-pretty text-muted-foreground">It opens here as soon as its pages are read, usually within a minute.</p>
      </div>
      <PreparationSteps steps={steps} />
      <Skeleton className="aspect-[8.5/11] w-full" />
    </div>
  )
}

function FailedGate({ paper, onUploaded, onRetrieved }: { paper: Paper; onUploaded: (accepted: UploadAccepted) => void; onRetrieved: (accepted: UploadAccepted) => void }) {
  const job = useFailedIngest(paper)
  const retry = useRetryJob()
  return (
    <div className="grid gap-6">
      <div className="grid gap-1.5">
        <h4 className="text-sm font-medium">This PDF couldn’t be processed</h4>
        <p className="text-sm text-muted-foreground">{job?.error?.message ?? 'Text-based PDFs work best. Scanned pages need text recognition, which is turned off.'}</p>
      </div>
      {job && (
        <div className="grid justify-items-start gap-3">
          <Button variant="outline" size="sm" disabled={retry.isPending} onClick={() => retry.mutate(job.id)}><RotateCcw data-icon="inline-start" aria-hidden="true" />{retry.isPending ? 'Retrying…' : 'Retry processing'}</Button>
          <ErrorNotice error={retry.error} />
        </div>
      )}
      <FullTextAccess paper={paper} onAccepted={onRetrieved} />
      <UploadDropzone paperId={paper.id} title="Upload a different PDF" chooseLabel="Upload PDF" onAccepted={onUploaded} />
    </div>
  )
}

/** What the reader shows until the paper has a readable PDF: attach it, follow its preparation, or recover. */
export function ReaderGate({ paper }: { paper: Paper }) {
  // An upload started here, or on the page that opened this one, is followed from its own job, even before the
  // paper itself reports that it is processing.
  const handedOver = (useLocation().state as { upload?: { jobId?: string } } | null)?.upload?.jobId
  const [started, setStarted] = useState<{ jobId: string; uploaded: boolean } | null>(null)
  const onUploaded = (accepted: UploadAccepted) => setStarted({ jobId: accepted.job_id, uploaded: true })
  const onRetrieved = (accepted: UploadAccepted) => setStarted({ jobId: accepted.job_id, uploaded: false })
  const followed = started ?? (handedOver && paper.document_status === 'processing' ? { jobId: handedOver, uploaded: true } : null)
  // While retrieval brings the PDF, uploading your own copy is the secondary way; otherwise it is the main one.
  const coming = usePdfComing(paper)
  return (
    <div className="h-full overflow-y-auto bg-background px-4">
      {/* The paper's bibliography leads, as above a PDF (ARA-101); it carries the abstract. */}
      <PaperHeader paper={paper} />
      {/* The PDF section, as above a PDF: the bar's heading alone, with nothing yet to page or zoom, then the ways
          to get one, all on the header's left edge (ARA-101 follow-up). */}
      <div className="flex min-h-11 items-center py-1.5"><PdfHeading /></div>
      <div className="grid max-w-md gap-8 pt-2 pb-10">
        {paper.upload_match ? <MatchDecision paper={{ ...paper, upload_match: paper.upload_match }} />
          : followed ? <ProcessingGate paper={paper} jobId={followed.jobId} uploaded={followed.uploaded} onSettled={(failed) => { if (failed) setStarted(null) }} />
          : paper.document_status === 'processing' ? <ProcessingGate paper={paper} />
          : paper.document_status === 'failed' ? <FailedGate paper={paper} onUploaded={onUploaded} onRetrieved={onRetrieved} />
          : coming ? <><FullTextAccess paper={paper} onAccepted={onRetrieved} /><UploadDropzone paperId={paper.id} variant="secondary" chooseLabel="Upload your own copy instead" onAccepted={onUploaded} /></>
          : <><FullTextAccess paper={paper} onAccepted={onRetrieved} /><UploadDropzone paperId={paper.id} chooseLabel="Upload PDF" title="Attach the PDF to read, summarize and ask" description="Text-based PDF, up to 25 MB. The reader, summaries and answers all cite its pages." onAccepted={onUploaded} /></>}
      </div>
    </div>
  )
}
