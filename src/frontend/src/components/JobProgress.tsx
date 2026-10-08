import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Job } from '../api/types'
import { ErrorNotice, Loading } from './Feedback'
export function JobProgress({ jobId, onSettled }: { jobId: string; onSettled?: (job: Job) => void }) {
  const query = useQuery({ queryKey: ['job', jobId], queryFn: () => api<Job>(`/jobs/${jobId}`), refetchInterval: (query) => ['completed', 'failed'].includes(query.state.data?.state ?? '') ? false : 1500 })
  const job = query.data; const announced = useRef<string | null>(null)
  useEffect(() => { if (job && ['completed', 'failed'].includes(job.state)) { const key = `${job.id}:${job.state}`; if (announced.current !== key) { announced.current = key; onSettled?.(job) } } }, [job, onSettled])
  return <div className="job-progress" aria-live="polite">{query.isPending && <Loading>Waiting for processing status…</Loading>}<ErrorNotice error={query.error} retry={() => void query.refetch()}/>{job && <><p><strong>{job.state === 'completed' ? 'Completed' : job.state === 'failed' ? 'Processing failed' : job.stage || job.state}</strong> <span className="muted">{job.progress}%</span></p><progress max={100} value={job.progress} aria-label="Processing progress"/>{job.error && <p className="error-text">{job.error.message}</p>}</>}<Link to="/jobs">View processing jobs</Link></div>
}
