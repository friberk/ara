import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, ApiError, json } from '@/api/client'
import type { AutomaticFullText, FullTextAccepted, FullTextInput, FullTextStatus } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'
import { useJob } from './jobs'

export function useFullText(paperId: string | undefined) {
  const client = useQueryClient()
  const status = useQuery<FullTextStatus>({
    queryKey: queryKeys.fulltext(paperId ?? ''),
    queryFn: ({ signal }) => api(`/papers/${paperId}/fulltext`, { signal }),
    enabled: !!paperId,
    refetchInterval: (query) => {
      const data = query.state.data
      const ingest = client.getQueryData<{ state: string }>(queryKeys.jobs.detail(data?.ingest_job_id ?? ''))
      return ['queued', 'processing'].includes(data?.retrieval_job?.state ?? '') || (!!data?.ingest_job_id && (!ingest || ['queued', 'processing'].includes(ingest.state))) ? 1500 : false
    },
  })
  const ingest = useJob(status.data?.ingest_job_id)
  const retrievalState = status.data?.retrieval_job?.state
  const retrievalId = status.data?.retrieval_job?.id
  const ingestState = ingest.data?.state
  useEffect(() => {
    if (retrievalState === 'completed' || retrievalState === 'failed' || ingestState === 'completed' || ingestState === 'failed') {
      void client.invalidateQueries({ queryKey: queryKeys.papers.detail(paperId ?? '') })
    }
  }, [client, paperId, retrievalId, retrievalState, ingestState])
  return status
}
export function useRetrieveFullText(paperId: string) {
  const client = useQueryClient()
  return useMutation<FullTextAccepted, Error, FullTextInput>({
    mutationFn: (input) => api(`/papers/${paperId}/retrieve-fulltext`, json('POST', input)),
    retry: (count, error) => count < 2 && error instanceof ApiError && [0, 502, 503, 504].includes(error.status),
    retryDelay: 500,
    onSuccess: () => { void client.invalidateQueries({ queryKey: queryKeys.fulltext(paperId) }); void client.invalidateQueries({ queryKey: queryKeys.jobs.all }) },
  })
}

export const automaticFullTextKey = (paperId: string) => ['fulltext', paperId, 'automatic'] as const

/** Starts retrieval for a paper saved before automatic retrieval. The server answers every repeat with the same job, or none. */
export function useAutomaticFullText(paperId: string) {
  const client = useQueryClient()
  return useMutation<AutomaticFullText, Error, void>({
    mutationKey: automaticFullTextKey(paperId),
    mutationFn: () => api(`/papers/${paperId}/retrieve-fulltext/automatic`, { method: 'POST' }),
    retry: (count, error) => count < 2 && error instanceof ApiError && [0, 502, 503, 504].includes(error.status),
    retryDelay: 500,
    onSuccess: (result) => { if (result.job_id) { void client.invalidateQueries({ queryKey: queryKeys.fulltext(paperId) }); void client.invalidateQueries({ queryKey: queryKeys.jobs.all }) } },
  })
}
