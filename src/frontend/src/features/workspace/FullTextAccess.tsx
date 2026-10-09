import { useEffect, useRef } from 'react'
import { useMutationState, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, RotateCcw } from 'lucide-react'
import { providerLabels, type AutomaticFullText, type Paper, type UploadAccepted } from '@/api/types'
import { safeUrl } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { automaticFullTextKey, useAutomaticFullText, useFullText, useRetrieveFullText } from '@/hooks/queries/fulltext'
import { doiLink } from '@/features/research/paper-format'
import { useNow } from '@/features/activity/relative-time'
import { retrievalFailure, retrievalProgress, retryWait, waitText } from './fulltext-copy'

function RetrievalProgress({ label }: { label: string }) {
  return (
    <div role="status" className="grid gap-1">
      <p className="flex items-center gap-2 text-sm font-medium"><Spinner aria-hidden="true" />{label}</p>
      <p className="text-sm text-muted-foreground">The reader opens here as soon as the PDF is ready.</p>
    </div>
  )
}

/**
 * Getting the paper's PDF: progress while retrieval runs by itself, then what happened and what can help.
 * A paper saved before retrieval was automatic starts it once here; the server replays that request ever after.
 */
export function FullTextAccess({ paper, onAccepted }: { paper: Paper; onAccepted?: (accepted: UploadAccepted) => void }) {
  const client = useQueryClient()
  const status = useFullText(paper.id)
  const retrieve = useRetrieveFullText(paper.id)
  const { mutate: startAutomatic } = useAutomaticFullText(paper.id)
  // Shared by every view of this paper, so the reader and the Details tab ask the server once.
  const automatic = useMutationState({ filters: { mutationKey: automaticFullTextKey(paper.id) }, select: (mutation) => ({ status: mutation.state.status, data: mutation.state.data as AutomaticFullText | undefined, error: mutation.state.error }) }).at(-1)
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
  const pdfLink = [...(status.data?.locations ?? []), ...paper.sources].map((location) => safeUrl(location.pdf_url)).find(Boolean)
  const untried = status.isSuccess && !job && paper.document_status === 'metadata_only' && !paper.active_document_id
  const qualifies = untried && (!!pdfLink || !!paper.doi)
  useEffect(() => {
    if (qualifies && !client.getMutationCache().find({ mutationKey: automaticFullTextKey(paper.id) })) startAutomatic()
  }, [client, paper.id, qualifies, startAutomatic])
  // Until the started job is listed, the request itself is the progress.
  const starting = qualifies && (!automatic || automatic.status === 'pending' || (automatic.status === 'success' && !!automatic.data?.job_id))
  const active = job?.state === 'queued' || job?.state === 'processing'
  const semantic = safeUrl(paper.sources.find((source) => source.provider === 'semantic_scholar')?.external_url)
  const publisher = safeUrl(status.data?.locations?.find((location) => location.host_type === 'publisher')?.landing_page_url) ?? doiLink(paper.doi)?.href
  if (paper.document_status === 'ready') {
    const acquisition = status.data?.acquisition
    if (!acquisition) return null
    const version = typeof acquisition.version === 'string' ? ({ acceptedVersion: 'Accepted manuscript', submittedVersion: 'Submitted manuscript', publishedVersion: 'Published version' }[acquisition.version] ?? acquisition.version) : null
    const provider = acquisition.provider === 'openalex' || acquisition.provider === 'semantic_scholar' ? providerLabels[acquisition.provider] : null
    const license = typeof acquisition.license === 'string' ? acquisition.license : null
    return <p className="text-sm text-muted-foreground">{[provider && `Retrieved via ${provider}`, version, license && `License: ${license}`].filter(Boolean).join(' · ')}</p>
  }
  if (paper.active_document_id && documentId && paper.active_document_id !== documentId) return null
  if (job?.state === 'completed' && documentId && ingestId && paper.document_status !== 'failed') return <RetrievalProgress label="Opening the PDF" />
  if (!paper.sources.length && !paper.doi) return null
  if (active || starting) return <RetrievalProgress label={retrievalProgress(job, status.data?.source_host)} />
  const failure = job?.state === 'failed' ? retrievalFailure(job.result?.outcome, job.error?.message) : null
  const busy = retrieve.isPending || status.isPending
  const retry = () => retrieve.mutate({ request_id: crypto.randomUUID() })
  return (
    <div className="grid gap-3">
      {failure && (
        <div role="alert" className="grid gap-1">
          <p className="text-sm font-medium">{failure.title}</p>
          <p className="text-sm text-muted-foreground">{failure.detail}</p>
        </div>
      )}
      {wait > 0 && <p className="text-sm text-muted-foreground">Try again in {waitText(wait)}.</p>}
      <div className="flex flex-wrap items-center gap-2">
        {failure ? failure.retry && (
          <Button size="sm" variant="outline" disabled={busy || wait > 0} onClick={retry}>
            {retrieve.isPending ? <Spinner data-icon="inline-start" aria-hidden="true" /> : <RotateCcw data-icon="inline-start" aria-hidden="true" />}Try again
          </Button>
        ) : (
          <Button size="sm" disabled={busy} onClick={retry}>{retrieve.isPending ? 'Finding PDF…' : pdfLink ? 'Get PDF' : 'Find PDF'}</Button>
        )}
        {failure?.browser && pdfLink && <Button asChild variant="outline" size="sm"><a href={pdfLink} target="_blank" rel="noreferrer">Open PDF in browser<ExternalLink data-icon="inline-end" aria-hidden="true" /></a></Button>}
        {semantic && <Button asChild variant="ghost" size="sm"><a href={semantic} target="_blank" rel="noreferrer">Open Semantic Scholar</a></Button>}
        {publisher && <Button asChild variant="ghost" size="sm"><a href={publisher} target="_blank" rel="noreferrer">Open publisher</a></Button>}
      </div>
      <ErrorNotice error={retrieve.error ?? automatic?.error ?? status.error} />
    </div>
  )
}
