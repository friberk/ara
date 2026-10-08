import { useEffect, useRef } from 'react'
import type { Job } from '@/api/types'
import { useJob } from '@/hooks/queries/jobs'
import { Progress } from '@/components/ui/progress'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { cn } from '@/lib/utils'
import { jobStageLabel } from './job-labels'

/** Live progress for one durable job. onSettled fires once per job and terminal state. */
export function JobProgress({ jobId, onSettled, label = 'Processing progress', className }: { jobId: string; onSettled?: (job: Job) => void; label?: string; className?: string }) {
  const query = useJob(jobId)
  const job = query.data
  const announced = useRef<string | null>(null)
  useEffect(() => {
    if (job && (job.state === 'completed' || job.state === 'failed')) {
      const key = `${job.id}:${job.state}`
      if (announced.current !== key) { announced.current = key; onSettled?.(job) }
    }
  }, [job, onSettled])
  return (
    <div className={cn('grid gap-1.5', className)} aria-live="polite">
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className={cn('font-medium', job?.state === 'failed' && 'text-destructive')}>{job ? jobStageLabel(job) : 'Waiting for processing status…'}</span>
        {job && <span className="tabular text-xs text-muted-foreground">{job.progress}%</span>}
      </div>
      <Progress value={job?.progress ?? 0} aria-label={label} />
      {job?.error && <p className="text-sm text-destructive">{job.error.message}</p>}
    </div>
  )
}
