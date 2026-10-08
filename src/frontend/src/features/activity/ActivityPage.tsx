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
import { isActiveJob, jobKindLabels, jobStageLabel } from '@/components/jobs/job-labels'
import { useJobs, useRetryJob } from '@/hooks/queries/jobs'
import { cn } from '@/lib/utils'
import { segmentedGroup, segmentedItem } from '@/features/settings/segmented'
import { absoluteTime, relativeTime, useNow } from './relative-time'

type Filter = 'all' | 'active' | 'failed'
const filters: { value: Filter; label: string; matches: (job: JobView) => boolean }[] = [
  { value: 'all', label: 'All', matches: () => true },
  { value: 'active', label: 'Active', matches: isActiveJob },
  { value: 'failed', label: 'Failed', matches: (job) => job.state === 'failed' },
]
const emptyFilter: Record<Exclude<Filter, 'all'>, { title: string; text: string }> = {
  active: { title: 'Nothing is running', text: 'New uploads and summaries show their progress here while they run.' },
  failed: { title: 'No failed jobs', text: 'Every job so far finished without an error.' },
}
const states: Record<JobView['state'], { label: string; tone: string }> = {
  queued: { label: 'Queued', tone: 'bg-muted text-muted-foreground' },
  processing: { label: 'Running', tone: 'bg-warning-muted text-warning' },
  completed: { label: 'Completed', tone: 'bg-success-muted text-success' },
  failed: { label: 'Failed', tone: 'bg-destructive/10 text-destructive' },
}

// Background kinds without a product name (maintenance checks) still read as a sentence.
function kindLabel(kind: string) {
  const known = jobKindLabels[kind]
  if (known) return known
  const words = kind.replaceAll('_', ' ')
  return `${words.charAt(0).toUpperCase()}${words.slice(1)} job`
}

function JobTime({ job, now }: { job: JobView; now: number }) {
  const settled = job.state === 'completed' || job.state === 'failed'
  const at = settled ? job.updated_at : job.created_at
  const relative = relativeTime(at, now)
  if (!relative) return null
  const verb = job.state === 'completed' ? 'Finished' : job.state === 'failed' ? 'Failed' : 'Started'
  return <time dateTime={at} title={absoluteTime.format(new Date(at))}>{verb} {relative}</time>
}

function JobRow({ job, now }: { job: JobView; now: number }) {
  const retry = useRetryJob()
  const label = kindLabel(job.kind)
  const active = isActiveJob(job)
  const state = states[job.state]
  const canRetry = job.state === 'failed' && job.kind === 'ingest'
  return (
    <li className="grid gap-2 py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="grid min-w-0 gap-1">
          <h2 className="text-sm font-semibold">{label}</h2>
          {job.paper_id && (
            <Link to={`/papers/${job.paper_id}`} className="inline-flex min-w-0 items-center gap-1.5 rounded-sm text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              <FileText className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{job.paper_title?.trim() || 'Untitled paper'}</span>
            </Link>
          )}
        </div>
        <Badge variant="secondary" className={cn('shrink-0 font-normal', state.tone)}>{state.label}</Badge>
      </div>
      {active && (
        <div className="grid gap-1.5 pt-1">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span>{jobStageLabel(job)}</span>
            <span className="tabular text-xs text-muted-foreground">{job.progress}%</span>
          </div>
          <Progress value={job.progress} aria-label={`${label} progress`} />
        </div>
      )}
      {job.state === 'failed' && <p className="text-sm text-destructive">{job.error?.message ?? 'This job stopped before it finished.'}</p>}
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-2 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-3">
          <JobTime job={job} now={now} />
          {job.attempts > 1 && <span>Attempt {job.attempts}</span>}
        </div>
        {canRetry && (
          <Button variant="outline" size="sm" disabled={retry.isPending} onClick={() => retry.mutate(job.id, { onSuccess: () => toast.success('Processing queued again') })}>
            <RotateCcw aria-hidden="true" />{retry.isPending ? 'Retrying…' : 'Retry processing'}
          </Button>
        )}
      </div>
      <ErrorNotice error={retry.error} />
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
  const now = useNow()
  const [filter, setFilter] = useState<Filter>('all')
  const items = jobs.data?.items ?? []
  const matches = filters.find((item) => item.value === filter)?.matches ?? (() => true)
  const visible = items.filter(matches)
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <p className="text-sm text-pretty text-muted-foreground">PDF processing and summaries run in the background. Progress updates here, and you can leave this page while they work.</p>
      </header>
      <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-label="Filter activity" value={filter} onValueChange={(value) => { if (value) setFilter(value as Filter) }} className={cn(segmentedGroup, 'mt-8')}>
        {filters.map((item) => <ToggleGroupItem key={item.value} value={item.value} className={segmentedItem}>{item.label}</ToggleGroupItem>)}
      </ToggleGroup>
      <div className="mt-2">
        {jobs.isPending && <div role="status" className="divide-y"><span className="sr-only">Loading activity…</span>{Array.from({ length: 3 }, (_, index) => <RowSkeleton key={index} />)}</div>}
        <ErrorNotice error={jobs.error} retry={() => void jobs.refetch()} className="mt-4" />
        {jobs.data && !items.length && (
          <EmptyState icon={Activity} title="No activity yet" className="mt-10" action={<Button asChild variant="outline"><Link to="/library#upload">Upload a PDF</Link></Button>}>
            Uploading a PDF or generating a summary starts a job. Its progress appears here.
          </EmptyState>
        )}
        {items.length > 0 && !visible.length && filter !== 'all' && <EmptyState title={emptyFilter[filter].title} className="mt-10">{emptyFilter[filter].text}</EmptyState>}
        {visible.length > 0 && <ul aria-label="Jobs" className="divide-y">{visible.map((job) => <JobRow key={job.id} job={job} now={now} />)}</ul>}
      </div>
    </div>
  )
}
