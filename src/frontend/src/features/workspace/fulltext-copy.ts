import type { Job } from '@/api/types'

// Names for the default FULLTEXT_ALLOWED_HOSTS; any other host is shown as it is.
const sources: Record<string, string> = {
  'arxiv.org': 'arXiv',
  'export.arxiv.org': 'arXiv',
  'aclanthology.org': 'ACL Anthology',
  'pmc.ncbi.nlm.nih.gov': 'PubMed Central',
  'europepmc.org': 'Europe PMC',
  'proceedings.neurips.cc': 'NeurIPS Proceedings',
  'openaccess.thecvf.com': 'CVF Open Access',
  'pdfs.semanticscholar.org': 'Semantic Scholar',
  'link.springer.com': 'Springer',
  'static-content.springer-cdn.com': 'Springer',
  'www.nature.com': 'Nature',
  'nature.com': 'Nature',
  'ieeexplore.ieee.org': 'IEEE Xplore',
  'dl.acm.org': 'ACM Digital Library',
}

export function sourceName(host: string | null | undefined): string | null {
  if (!host) return null
  return sources[host] ?? host.replace(/^www\./, '')
}

/** One line for an automatic retrieval in progress. */
export function retrievalProgress(job: Pick<Job, 'state' | 'stage'> | null | undefined, host?: string | null): string {
  const source = sourceName(host)
  switch (job?.stage) {
    case 'fetching_pdf': return source ? `Downloading the PDF from ${source}` : 'Downloading the PDF'
    case 'storing_pdf': return 'Saving the PDF'
    case 'retry_wait': return 'Trying again shortly'
    default: return 'Looking for an open PDF'
  }
}

export type RetrievalFailure = {
  title: string
  detail: string
  /** A fresh attempt can succeed: the cause is transient or depends on the network. */
  retry: boolean
  /** Downloading the copy in a browser and uploading it is the way forward. */
  browser: boolean
}

const network = 'If your university has access, try again on its network or VPN, or open the PDF in your browser and upload it here.'

export function retrievalFailure(outcome: unknown, reason?: string | null): RetrievalFailure {
  switch (outcome) {
    case 'access_required': return { title: 'This PDF needs a sign-in', detail: `The site asked for a sign-in, which the app can’t borrow from your browser. ${network}`, retry: true, browser: true }
    case 'blocked': return { title: 'The source blocked the download', detail: `The site refused the app’s download. ${network}`, retry: true, browser: true }
    case 'rate_limited': return { title: 'Too many requests right now', detail: reason || 'The source asked for a pause before the next request.', retry: true, browser: false }
    case 'invalid_pdf': return { title: 'The link didn’t return a usable PDF', detail: 'It returned a web page or an unreadable file. Open it in your browser, download the PDF and upload it here.', retry: false, browser: true }
    case 'unsupported_source': return { title: 'Automatic downloads aren’t enabled for this site', detail: 'Open the PDF in your browser, download it and upload it here.', retry: false, browser: true }
    case 'unsafe_url': return { title: 'This link can’t be downloaded safely', detail: 'Check the publisher page or upload a PDF.', retry: false, browser: false }
    case 'not_found': return { title: 'The PDF link no longer works', detail: 'Check the publisher page or upload a copy.', retry: false, browser: false }
    case 'no_pdf_link': return { title: 'No open PDF was found', detail: 'OpenAlex and Semantic Scholar list no downloadable copy. Check the publisher page or upload a PDF.', retry: false, browser: false }
    default: return { title: 'The PDF couldn’t be reached right now', detail: 'The source or the paper lookup didn’t respond. Try again in a moment, or upload a PDF.', retry: true, browser: false }
  }
}

export function retryWait(job: Pick<Job, 'result' | 'updated_at'> | null | undefined, now: number): number {
  if (job?.result?.outcome !== 'rate_limited' || typeof job.result.retry_after !== 'number') return 0
  const at = Date.parse(job.updated_at)
  return Number.isFinite(at) ? Math.max(0, Math.ceil((at + Math.min(300, Math.max(0, job.result.retry_after)) * 1000 - now) / 1000)) : 0
}

export function waitText(seconds: number): string {
  if (seconds < 90) return `${seconds} ${seconds === 1 ? 'second' : 'seconds'}`
  return `${Math.ceil(seconds / 60)} minutes`
}
