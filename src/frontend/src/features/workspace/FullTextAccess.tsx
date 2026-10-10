import { useEffect, useRef } from 'react'
import { useMutationState, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, RotateCcw } from 'lucide-react'
import { providerLabels, type AutomaticFullText, type Paper, type UploadAccepted } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { automaticFullTextKey, useAutomaticFullText, useFullText, useRetrieveFullText } from '@/hooks/queries/fulltext'
import { doiLink } from '@/features/research/paper-format'
import { useNow } from '@/lib/relative-time'
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
 * Getting the paper's PDF from OpenAlex's stored copies (ARA-087): progress while retrieval runs by itself, else
 * the DOI link and a request to upload the PDF. A paper saved before retrieval was automatic starts it once here;
 * the server replays that request ever after.
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
  const keyed = status.data?.api_key_configured === true
  const untried = status.isSuccess && !job && paper.document_status === 'metadata_only' && !paper.active_document_id
  // OpenAlex finds the work from its saved record or from the DOI.
  const qualifies = untried && keyed && (paper.sources.some((source) => source.provider === 'openalex') || !!paper.doi)
  useEffect(() => {
    if (qualifies && !client.getMutationCache().find({ mutationKey: automaticFullTextKey(paper.id) })) startAutomatic()
  }, [client, paper.id, qualifies, startAutomatic])
  // Until the started job is listed, the request itself is the progress.
  const starting = qualifies && (!automatic || automatic.status === 'pending' || (automatic.status === 'success' && !!automatic.data?.job_id))
  const active = job?.state === 'queued' || job?.state === 'processing'
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
  if (active || starting) return <RetrievalProgress label={retrievalProgress(job)} />
  // Until the status arrives it is unknown whether retrieval will start, so offer nothing yet.
  if (status.isPending) return null
  const paperLink = doiLink(paper.doi)?.href
  // Without a DOI there is nothing to open, so the reader's upload is the only step.
  if (!paperLink) return null
  const failure = job?.state === 'failed' ? retrievalFailure(job.result?.outcome, job.error?.message) : null
  const retry = () => retrieve.mutate({ request_id: crypto.randomUUID() })
  return (
    <div className="grid gap-3">
      <div role={failure ? 'alert' : undefined} className="grid gap-1">
        {failure && <p className="text-sm font-medium">{failure.title}</p>}
        <p className="text-sm text-muted-foreground">{[failure?.detail, 'Open the paper from its DOI, download the PDF and upload it here.'].filter(Boolean).join(' ')}</p>
      </div>
      {wait > 0 && <p className="text-sm text-muted-foreground">Try again in {waitText(wait)}.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="outline" size="sm"><a href={paperLink} target="_blank" rel="noreferrer">Open the paper<ExternalLink data-icon="inline-end" aria-hidden="true" /></a></Button>
        {failure?.retry && keyed && (
          <Button variant="ghost" size="sm" disabled={retrieve.isPending || wait > 0} onClick={retry}>
            {retrieve.isPending ? <Spinner data-icon="inline-start" aria-hidden="true" /> : <RotateCcw data-icon="inline-start" aria-hidden="true" />}Try again
          </Button>
        )}
      </div>
      {status.data?.api_key_configured === false && <p className="text-xs text-muted-foreground">Add an OpenAlex API key on the server to download stored PDFs automatically.</p>}
      <ErrorNotice error={retrieve.error ?? automatic?.error ?? status.error} />
    </div>
  )
}
