import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { DocumentState, Job } from '@/api/types'
import { useJob, useJobs } from '@/hooks/queries/jobs'
import { usePaperLookup } from '@/hooks/queries/metadata'
import { queryKeys } from '@/lib/query-keys'
import { preparationSteps } from './preparation'

/**
 * Steps for a paper's newest PDF from its jobs: the ingest job the caller started, else the paper's active one, then
 * the catalog lookup. Without a known document state the ingest job stands in for it. onSettled fires once per job
 * and terminal state, after the paper is asked to refresh.
 */
export function usePreparation({ paperId, documentStatus, jobId, uploaded, onSettled }: { paperId: string; documentStatus?: DocumentState; jobId?: string; uploaded?: boolean; onSettled?: (job: Job) => void }) {
  const client = useQueryClient()
  const followed = useJob(jobId)
  const listed = useJobs({ paperId, kind: 'ingest', active: true }, { enabled: !jobId && documentStatus === 'processing' })
  const ingest = followed.data ?? listed.data?.items.find((job) => job.kind === 'ingest' && job.paper_id === paperId && job.state !== 'failed') ?? null
  const status: DocumentState = documentStatus ?? (ingest?.state === 'completed' ? 'ready' : ingest?.state === 'failed' ? 'failed' : 'processing')
  const lookup = usePaperLookup({ id: paperId, document_status: status })
  const notify = useRef(onSettled)
  useEffect(() => { notify.current = onSettled })
  const settled = useRef<string | null>(null)
  useEffect(() => {
    if (!ingest || (ingest.state !== 'completed' && ingest.state !== 'failed')) return
    const key = `${ingest.id}:${ingest.state}`
    if (settled.current === key) return
    settled.current = key
    void client.invalidateQueries({ queryKey: queryKeys.papers.detail(paperId) })
    notify.current?.(ingest)
  }, [ingest, client, paperId])
  return preparationSteps({ uploaded, ingest, lookup, documentStatus: status })
}
