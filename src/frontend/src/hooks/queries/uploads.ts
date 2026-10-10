import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, checkedResponse, json } from '@/api/client'
import type { Collection, MatchDecision, Paper } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'
import { useFullText } from './fulltext'

// Under the papers prefix, so whatever refreshes the library refreshes these too (ARA-086).
const matchesKey = [...queryKeys.papers.all, 'upload-matches'] as const

/** Uploads that matched a library paper and wait for Replace/Attach or Cancel. */
export function usePendingMatches() {
  return useQuery({ queryKey: matchesKey, queryFn: ({ signal }) => api<Collection<Paper>>('/uploads/matches', { signal }) })
}

/** Attach (or replace) answers with the library paper; discard answers with nothing. */
export function useResolveMatch(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (decision: MatchDecision): Promise<Paper | null> => {
      const response = await checkedResponse(`/uploads/${encodeURIComponent(paperId)}/match`, json('POST', { decision }))
      return response.status === 204 ? null : response.json() as Promise<Paper>
    },
    onSuccess: (paper) => {
      if (paper) client.setQueryData(queryKeys.papers.detail(paper.id), paper)
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      void client.invalidateQueries({ queryKey: queryKeys.jobs.all })
    },
  })
}

/** A paper without a PDF whose automatic retrieval is queued or running: its PDF is on its way. */
export function usePdfComing(paper: Pick<Paper, 'id' | 'document_status'>) {
  const status = useFullText(paper.document_status === 'metadata_only' ? paper.id : undefined)
  const state = status.data?.retrieval_job?.state
  return paper.document_status === 'metadata_only' && (state === 'queued' || state === 'processing')
}
