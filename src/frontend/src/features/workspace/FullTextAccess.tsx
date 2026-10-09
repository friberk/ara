import { useEffect, useRef } from 'react'
import { providerLabels, type Paper, type UploadAccepted } from '@/api/types'
import { safeUrl } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useFullText, useRetrieveFullText } from '@/hooks/queries/fulltext'
import { doiLink } from '@/features/research/paper-format'
import { jobStageLabel } from '@/components/jobs/job-labels'
import { useNow } from '@/features/activity/relative-time'
import { retrievalMessage, retryWait } from './fulltext-copy'

export function FullTextAccess({ paper, onAccepted }: { paper: Paper; onAccepted?: (accepted: UploadAccepted) => void }) {
  const status = useFullText(paper.id)
  const retrieve = useRetrieveFullText(paper.id)
  const job = status.data?.retrieval_job
  const handedOff = useRef<string | null>(null)
  const now = useNow(1000)
  const wait = retryWait(job, now)
  const documentId = status.data?.document_id
  const ingestId = status.data?.ingest_job_id
  useEffect(() => {
    const key = `${paper.id}:${documentId}:${ingestId}`
    if (paper.document_status !== 'ready' && paper.document_status !== 'failed' && (!paper.active_document_id || paper.active_document_id === documentId) && job?.state === 'completed' && documentId && ingestId && handedOff.current !== key && onAccepted) {
      handedOff.current = key
      onAccepted({ paper_id: paper.id, document_id: documentId, job_id: ingestId })
    }
  }, [paper.id, paper.document_status, paper.active_document_id, job?.state, documentId, ingestId, onAccepted])
  const active = job?.state === 'queued' || job?.state === 'processing'
  const direct = status.data?.locations?.some((location) => safeUrl(location.pdf_url)) || paper.sources.some((source) => safeUrl(source.pdf_url))
  const semantic = safeUrl(paper.sources.find((source) => source.provider === 'semantic_scholar')?.external_url)
  const publisher = safeUrl(status.data?.locations?.find((location) => location.host_type === 'publisher')?.landing_page_url) ?? doiLink(paper.doi)?.href
  const failed = job?.state === 'failed'
  if (paper.document_status === 'ready') {
    const acquisition = status.data?.acquisition
    if (!acquisition) return null
    const version = typeof acquisition.version === 'string' ? ({ acceptedVersion: 'Accepted manuscript', submittedVersion: 'Submitted manuscript', publishedVersion: 'Published version' }[acquisition.version] ?? acquisition.version) : null
    const provider = acquisition.provider === 'openalex' || acquisition.provider === 'semantic_scholar' ? providerLabels[acquisition.provider] : null
    const license = typeof acquisition.license === 'string' ? acquisition.license : null
    return <p className="text-sm text-muted-foreground">{[provider && `Retrieved via ${provider}`, version, license && `License: ${license}`].filter(Boolean).join(' · ')}</p>
  }
  if (paper.active_document_id && documentId && paper.active_document_id !== documentId) return null
  if (job?.state === 'completed' && documentId && ingestId && paper.document_status !== 'failed') return <p role="status" className="text-sm text-muted-foreground">PDF downloaded. Processing its pages continues in the background.</p>
  if (!paper.sources.length && !paper.doi) return null
  return <div className="grid gap-3">
    {active && <><p role="status" className="text-sm font-medium">{jobStageLabel(job)}</p><p className="text-sm text-muted-foreground">This continues in the background. You can leave this page.</p></>}
    {failed && <>
      <div role="alert" className="grid gap-3">
      <p className="text-sm">{retrievalMessage(job.result?.outcome)}</p>
      {['blocked', 'access_required'].includes(String(job.result?.outcome)) && <p className="text-sm text-muted-foreground">If your university provides access, connect to its network or supported VPN and retry. The app downloads using the network of the computer running its backend. Browser sign-in does not sign the app in; you can download there and upload here.</p>}
      </div>
      {wait > 0 && <p className="text-sm text-muted-foreground">Try again in {wait} seconds.</p>}
    </>}
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" disabled={retrieve.isPending || active || status.isPending || wait > 0} onClick={() => retrieve.mutate({ request_id: crypto.randomUUID() })}>{active || retrieve.isPending ? 'Finding PDF…' : failed ? 'Retry download' : direct ? 'Get PDF' : 'Find PDF'}</Button>
      {semantic && <Button asChild variant="ghost" size="sm"><a href={semantic} target="_blank" rel="noreferrer">Open Semantic Scholar</a></Button>}
      {publisher && <Button asChild variant="ghost" size="sm"><a href={publisher} target="_blank" rel="noreferrer">Open publisher</a></Button>}
    </div>
    <ErrorNotice error={retrieve.error ?? status.error} />
  </div>
}
