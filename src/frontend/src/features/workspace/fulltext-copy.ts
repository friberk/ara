import type { Job } from '@/api/types'

/** One line for a retrieval in progress; PDFs come only from OpenAlex's stored copies. */
export function retrievalProgress(job: Pick<Job, 'state' | 'stage'> | null | undefined): string {
  switch (job?.stage) {
    case 'fetching_pdf': return 'Downloading the PDF from OpenAlex'
    case 'storing_pdf': return 'Saving the PDF'
    case 'retry_wait': return 'Trying again shortly'
    default: return 'Checking OpenAlex for a stored PDF'
  }
}

export type RetrievalFailure = {
  title: string
  /** Shown before the request to open the paper from its DOI and upload the PDF. */
  detail?: string
  /** A fresh attempt can succeed: the cause is transient. */
  retry: boolean
}

export function retrievalFailure(outcome: unknown, reason?: string | null): RetrievalFailure {
  switch (outcome) {
    case 'not_stored': return { title: 'OpenAlex doesn’t have this PDF', detail: 'It may be paywalled or not stored yet.', retry: false }
    case 'rate_limited': return { title: 'OpenAlex is limiting requests', detail: reason || undefined, retry: true }
    case 'unavailable': return { title: 'OpenAlex couldn’t be reached', retry: true }
    case 'invalid_pdf': return { title: 'OpenAlex’s copy isn’t a usable PDF', retry: false }
    case 'unsafe_url': return { title: 'OpenAlex’s link couldn’t be followed safely', retry: false }
    case 'api_key_required': return { title: 'OpenAlex didn’t accept the API key', detail: 'Check OPENALEX_API_KEY on the server.', retry: false }
    // Outcomes of the retired multi-host downloader, kept by older jobs.
    default: return { title: 'The PDF couldn’t be downloaded', retry: true }
  }
}

/** Seconds left of the wait OpenAlex reported; a spent daily allowance can mean hours. */
export function retryWait(job: Pick<Job, 'result' | 'updated_at'> | null | undefined, now: number): number {
  if (job?.result?.outcome !== 'rate_limited' || typeof job.result.retry_after !== 'number') return 0
  const at = Date.parse(job.updated_at)
  return Number.isFinite(at) ? Math.max(0, Math.ceil((at + Math.min(86_400, Math.max(0, job.result.retry_after)) * 1000 - now) / 1000)) : 0
}

export function waitText(seconds: number): string {
  if (seconds < 90) return `${seconds} ${seconds === 1 ? 'second' : 'seconds'}`
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} minutes`
  const hours = Math.ceil(seconds / 3600)
  return `${hours} ${hours === 1 ? 'hour' : 'hours'}`
}
