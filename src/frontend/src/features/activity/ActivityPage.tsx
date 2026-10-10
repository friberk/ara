import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, FileText, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import type { JobView } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { isActiveJob, isCancelledJob, jobKindLabels, jobStageLabel } from '@/components/jobs/job-labels'
import { useJobs, useRetryJob } from '@/hooks/queries/jobs'
import { useOpenModels } from '@/hooks/queries/features'
import { useModels } from '@/hooks/queries/models'
import { useRetrieveFullText } from '@/hooks/queries/fulltext'
import { cn } from '@/lib/utils'
import { segmentedGroup, segmentedItem } from '@/features/settings/segmented'
import { absoluteTime, relativeTime, useNow } from './relative-time'
import { retryWait } from '@/features/workspace/fulltext-copy'

type Filter = 'all' | 'active' | 'failed'
const filters: { value: Filter; label: string; matches: (job: JobView) => boolean }[] = [
  { value: 'all', label: 'All', matches: () => true },
  { value: 'active', label: 'Active', matches: isActiveJob },
  { value: 'failed', label: 'Failed', matches: (job) => job.state === 'failed' && !isCancelledJob(job) },
]
const emptyFilter = (openModels: boolean): Record<Exclude<Filter, 'all'>, { title: string; text: string }> => ({
  active: { title: 'Nothing is running', text: openModels ? 'Uploads, summaries and model downloads show their progress here.' : 'Uploads and summaries show their progress here.' },
  failed: { title: 'No failed jobs', text: 'Every job so far finished without an error.' },
})
const states: Record<JobView['state'], { label: string; tone: string }> = {
  queued: { label: 'Queued', tone: 'bg-muted text-muted-foreground' },
  processing: { label: 'Running', tone: 'bg-warning-muted text-warning' },
  paused: { label: 'Paused', tone: 'bg-muted text-muted-foreground' },
  completed: { label: 'Completed', tone: 'bg-success-muted text-success' },
  failed: { label: 'Failed', tone: 'bg-destructive/10 text-destructive' },
}
const cancelled = { label: 'Cancelled', tone: 'bg-muted text-muted-foreground' }
// Failed work the reader can queue again, and what its button says.
const retries: Record<string, { action: string; queued: string }> = {
  ingest: { action: 'Retry processing', queued: 'Processing queued again' },
  storage_cleanup: { action: 'Retry cleanup', queued: 'Cleanup queued again' },
}

// Only work the reader started is shown; maintenance jobs such as the deployment canary stay internal.
const isReaderJob = (job: JobView) => job.kind in jobKindLabels
// Local model downloads and deletions exist only while open models are on (ARA-090).
const isModelJob = (job: JobView) => job.kind === 'model_download' || job.kind === 'model_delete'
const kindLabel = (kind: string) => jobKindLabels[kind] ?? kind

function JobTime({ job, now }: { job: JobView; now: number }) {
  const settled = job.state === 'completed' || job.state === 'failed'
  const at = settled ? job.updated_at : job.created_at
  const relative = relativeTime(at, now)
  if (!relative) return null
  const verb = job.state === 'completed' ? 'Finished' : isCancelledJob(job) ? 'Stopped' : job.state === 'failed' ? 'Failed' : 'Started'
  return <time dateTime={at} title={absoluteTime.format(new Date(at))}>{verb} {relative}</time>
}

function JobRow({ job, now, modelName }: { job: JobView; now: number; modelName?: string }) {
  const retry = useRetryJob()
  const download = useRetrieveFullText(job.paper_id ?? '')
  const wait = retryWait(job, now)
  const preparation = job.model_operation === 'verify'
  const label = preparation ? 'Model preparation' : kindLabel(job.kind)
  const active = isActiveJob(job)
  const stopped = isCancelledJob(job)
  const state = stopped ? cancelled : states[job.state]
  const retryable = job.state === 'failed' && !stopped ? retries[job.kind] : undefined
  const progress = job.model_key ? (job.total_bytes ? Math.min(99, Math.floor(100 * (job.completed_bytes ?? 0) / job.total_bytes)) : null) : job.progress
  return (
    <li className="grid gap-2 py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="grid min-w-0 gap-1">
          <h2 className="text-sm font-semibold">{label}</h2>
          {job.model_key && <Link to="/settings#local-models" className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">{modelName ?? 'Manage local model'}</Link>}
          {job.paper_id ? (
            <Link to={`/papers/${job.paper_id}`} className="inline-flex min-w-0 items-center gap-1.5 rounded-sm text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              <FileText className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{job.paper_title?.trim() || 'Untitled paper'}</span>
            </Link>
          ) : job.paper_title && (
            // A deleted paper is named without a link that would lead nowhere (ARA-095).
            <span className="inline-flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
              <FileText className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{`${job.paper_title.trim() || 'Untitled paper'} (deleted)`}</span>
            </span>
          )}
        </div>
        <Badge variant="secondary" className={cn('shrink-0 font-normal', state.tone)}>{state.label}</Badge>
      </div>
      {active && preparation && (
        <div className="grid gap-1 pt-1 text-sm text-muted-foreground">
          <p role="status">{job.stage === 'verifying' ? 'Checking model readiness.' : 'Waiting to check model readiness.'}</p>
          <p className="text-xs">Preparation continues in the background. You can leave this page.</p>
        </div>
      )}
      {active && !preparation && (
        <div className="grid gap-1.5 pt-1">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span>{jobStageLabel(job)}</span>
            {progress !== null && <span className="tabular text-xs text-muted-foreground">{progress}%</span>}
          </div>
          <Progress value={progress} aria-label={`${label} progress`} />
        </div>
      )}
      {job.state === 'failed' && <p className={cn('text-sm', stopped ? 'text-muted-foreground' : 'text-destructive')}>{job.error?.message ?? 'This job stopped before it finished.'}</p>}
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-2 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-3">
          <JobTime job={job} now={now} />
          {job.attempts > 1 && <span>Attempt {job.attempts}</span>}
        </div>
        {retryable && (
          <Button variant="outline" size="sm" disabled={retry.isPending} onClick={() => retry.mutate(job.id, { onSuccess: () => toast.success(retryable.queued) })}>
            <RotateCcw aria-hidden="true" />{retry.isPending ? 'Retrying…' : retryable.action}
          </Button>
        )}
        {job.state === 'failed' && job.kind === 'fulltext' && job.paper_id && <div className="flex flex-wrap items-center gap-2">{wait > 0 && <span>Try again in {wait} seconds.</span>}<Button variant="outline" size="sm" disabled={download.isPending || wait > 0} onClick={() => download.mutate({ request_id: crypto.randomUUID() }, { onSuccess: () => toast.success('PDF retrieval queued again') })}><RotateCcw aria-hidden="true" />{download.isPending ? 'Retrying…' : 'Retry download'}</Button></div>}
      </div>
      <ErrorNotice error={retry.error} />
      <ErrorNotice error={download.error} />
    </li>
  )
}

function RowSkeleton() {
  return (
    <div className="grid gap-2 py-5">
      <div className="flex justify-between"><Skeleton className="h-4 w-32" /><Skeleton className="h-5 w-20 rounded-full" /></div>
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-3 w-24" />
    </div>
  )
}

/** Durable background work: PDF processing and summaries, polled while any job is still running. */
export default function ActivityPage() {
  const jobs = useJobs()
  const models = useModels()
  const now = useNow(1000)
  const openModels = useOpenModels()
  const [filter, setFilter] = useState<Filter>('all')
  const items = (jobs.data?.items ?? []).filter((job) => isReaderJob(job) && (openModels || !isModelJob(job)))
  const matches = filters.find((item) => item.value === filter)?.matches ?? (() => true)
  const visible = items.filter(matches)
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <p className="text-sm text-pretty text-muted-foreground">{openModels ? 'PDF processing, summaries and model downloads run' : 'PDF processing and summaries run'} in the background. Progress updates here, and you can leave this page while they work.</p>
      </header>
      <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-label="Filter activity" value={filter} onValueChange={(value) => { if (value) setFilter(value as Filter) }} className={cn(segmentedGroup, 'mt-8')}>
        {filters.map((item) => <ToggleGroupItem key={item.value} value={item.value} className={segmentedItem}>{item.label}</ToggleGroupItem>)}
      </ToggleGroup>
      <div className="mt-2">
        {jobs.isPending && <div role="status" className="divide-y"><span className="sr-only">Loading activity…</span>{Array.from({ length: 3 }, (_, index) => <RowSkeleton key={index} />)}</div>}
        <ErrorNotice error={jobs.error} retry={() => void jobs.refetch()} className="mt-4" />
        {jobs.data && !items.length && (
          <EmptyState icon={Activity} title="No activity yet" className="mt-10" action={<Button asChild variant="outline"><Link to="/library#upload">Upload a PDF</Link></Button>}>
            {openModels ? 'Uploading a PDF, generating a summary or downloading model weights starts a job.' : 'Uploading a PDF or generating a summary starts a job.'} Its progress appears here.
          </EmptyState>
        )}
        {items.length > 0 && !visible.length && filter !== 'all' && <EmptyState title={emptyFilter(openModels)[filter].title} className="mt-10">{emptyFilter(openModels)[filter].text}</EmptyState>}
        {visible.length > 0 && <ul aria-label="Jobs" className="divide-y">{visible.map((job) => <JobRow key={job.id} job={job} now={now} modelName={models.data?.items.find((model) => model.key === job.model_key)?.display_name} />)}</ul>}
      </div>
    </div>
  )
}
