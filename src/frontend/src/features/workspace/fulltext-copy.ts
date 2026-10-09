import type { Job } from '@/api/types'

export function retrievalMessage(outcome: unknown): string {
  switch (outcome) {
    case 'access_required': return 'This source requires authentication. Your university may provide access.'
    case 'blocked': return 'This site blocked the download. Institutional access or downloading in your browser may help.'
    case 'invalid_pdf': return 'This source returned a web page instead of a PDF, or an invalid PDF. Try downloading in your browser.'
    case 'rate_limited': return 'This source limited download requests. Wait before trying again.'
    case 'not_found': return 'This PDF link is no longer available. Try the publisher or upload a copy.'
    case 'unsupported_source': return 'Download this copy in your browser, then upload it here. This source isn’t supported for automatic downloads.'
    case 'unsafe_url': return 'The app couldn’t safely download from this link. Open the source in your browser or upload a PDF.'
    case 'no_pdf_link': return 'No direct PDF link was found. Open the publisher or Semantic Scholar to look for a copy.'
    default: return 'The source or paper lookup is temporarily unavailable. You can retry or upload a PDF.'
  }
}

export function retryWait(job: Pick<Job, 'result' | 'updated_at'> | null | undefined, now: number): number {
  if (job?.result?.outcome !== 'rate_limited' || typeof job.result.retry_after !== 'number') return 0
  const at = Date.parse(job.updated_at)
  return Number.isFinite(at) ? Math.max(0, Math.ceil((at + Math.min(300, Math.max(0, job.result.retry_after)) * 1000 - now) / 1000)) : 0
}
