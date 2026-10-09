import type { Job } from '@/api/types'

export const jobKindLabels: Record<string, string> = { ingest: 'PDF processing', summary: 'Paper summary', model_download: 'Model download', model_delete: 'Model weights deletion' }
const stageLabels: Record<string, string> = {
  queued: 'Waiting to start',
  processing: 'Reading the PDF',
  extracting_metadata: 'Extracting title, authors and abstract',
  summarizing: 'Summarizing sections',
  combining: 'Combining the summary',
  retry_wait: 'Waiting to retry',
  inventory: 'Checking installed weights',
  recovering: 'Restoring download progress',
  settling: 'Stopping download',
  compressing: 'Shortening summary sections',
  downloading: 'Downloading weights',
  pausing: 'Stopping the transfer',
  paused: 'Paused',
  verifying: 'Verifying model readiness',
  deleting: 'Deleting weights',
  completed: 'Completed',
  failed: 'Failed',
}

export function jobKindLabel(kind: string) { return jobKindLabels[kind] ?? kind.replaceAll('_', ' ') }
export function jobStageLabel(job: Pick<Job, 'state' | 'stage'>) {
  if (job.state === 'completed') return 'Completed'
  if (job.state === 'failed') return 'Processing failed'
  return stageLabels[job.stage] ?? (job.stage ? job.stage.replaceAll('_', ' ') : stageLabels[job.state] ?? job.state)
}
export const isActiveJob = (job: Pick<Job, 'state'>) => job.state === 'queued' || job.state === 'processing' || job.state === 'paused'
