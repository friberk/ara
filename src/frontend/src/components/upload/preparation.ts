import type { DocumentState, Job } from '@/api/types'

export type StepState = 'done' | 'active' | 'pending' | 'failed'
export type PreparationStep = { key: 'upload' | 'read' | 'details' | 'ready'; label: string; state: StepState; detail?: string }
type JobLike = Pick<Job, 'state' | 'stage' | 'error'>

const active = (job: JobLike | null | undefined) => job?.state === 'queued' || job?.state === 'processing'

/**
 * The one sequence a new PDF goes through, whatever its source: Uploading (only when this view sent it), Reading
 * pages, Finding paper details, Ready. The catalog lookup runs after the PDF is readable, so a ready paper can still
 * be finding its details; it never blocks reading.
 */
export function preparationSteps({ upload, uploaded, ingest, lookup, documentStatus }: {
  upload?: { progress: number }
  uploaded?: boolean
  ingest?: JobLike | null
  lookup?: JobLike | null
  documentStatus: DocumentState
}): PreparationStep[] {
  const steps: PreparationStep[] = []
  if (upload) steps.push({ key: 'upload', label: 'Uploading', state: 'active', detail: `${Math.round(upload.progress * 100)}%` })
  else if (uploaded) steps.push({ key: 'upload', label: 'Uploaded', state: 'done' })
  const failed = !upload && (ingest?.state === 'failed' || documentStatus === 'failed')
  const ready = !upload && !active(ingest) && documentStatus === 'ready'
  const read = !upload && (ready || ingest?.state === 'completed' || ingest?.stage === 'extracting_metadata')
  steps.push(
    upload ? { key: 'read', label: 'Reading pages', state: 'pending' }
      : failed ? { key: 'read', label: 'Reading pages', state: 'failed', detail: ingest?.error?.message }
      : { key: 'read', label: 'Reading pages', state: read ? 'done' : 'active' },
  )
  let details: PreparationStep = { key: 'details', label: 'Finding paper details', state: 'pending' }
  if (upload || failed) details = { ...details, state: 'pending' }
  else if (active(lookup)) details = { ...details, state: 'active', detail: lookup?.stage === 'retry_wait' ? 'Catalog busy, trying again shortly' : undefined }
  else if (ingest?.stage === 'extracting_metadata' && !ready) details = { ...details, state: 'active' }
  else if (ready && lookup?.state === 'failed') details = { ...details, state: 'done', detail: 'Kept the details from the PDF' }
  else if (ready) details = { ...details, state: 'done' }
  steps.push(details, { key: 'ready', label: 'Ready', state: ready ? 'done' : 'pending' })
  return steps
}
