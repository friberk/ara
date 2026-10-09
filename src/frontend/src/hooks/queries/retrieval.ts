import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { EmbeddingProfilePage, PaperRetrieval, PaperRetrievalUpdate, RetrievalIndex, RetrievalSettings } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export function isBuilding(index: RetrievalIndex) { return index.state === 'queued' || index.state === 'embedding' }

/** Search models a paper can be indexed with, with install status. */
export function useEmbeddingProfiles() {
  return useQuery({ queryKey: queryKeys.retrieval.profiles, queryFn: ({ signal }) => api<EmbeddingProfilePage>('/retrieval/profiles', { signal }) })
}

/** Retrieval settings live apart from the chat model defaults in /settings. */
export function useRetrievalSettings() {
  return useQuery({ queryKey: queryKeys.retrieval.settings, queryFn: ({ signal }) => api<RetrievalSettings>('/retrieval/settings', { signal }) })
}

export function useSaveRetrievalSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (value: RetrievalSettings) => api<RetrievalSettings>('/retrieval/settings', json('PUT', value)),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.retrieval.settings, data)
      // The profile page reports the default it follows.
      void client.invalidateQueries({ queryKey: queryKeys.retrieval.profiles })
    },
  })
}

/** Which model a paper searches with and the state of its indexes; polls while any index is building. */
export function usePaperRetrieval(paperId: string) {
  return useQuery({
    queryKey: queryKeys.retrieval.paper(paperId),
    queryFn: ({ signal }) => api<PaperRetrieval>(`/papers/${encodeURIComponent(paperId)}/retrieval`, { signal }),
    refetchInterval: (current) => current.state.data?.indexes.some(isBuilding) ? 1500 : false,
  })
}

// Each user action carries its own request id, so a replayed delivery returns the same result instead of building twice.
export function useUpdatePaperRetrieval(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ profile }: { profile: string | null }) => api<PaperRetrieval>(`/papers/${encodeURIComponent(paperId)}/retrieval`, json('PUT', { profile, request_id: crypto.randomUUID() } satisfies PaperRetrievalUpdate)),
    onSuccess: (data) => client.setQueryData(queryKeys.retrieval.paper(paperId), data),
  })
}

export function useRebuildPaperRetrieval(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<PaperRetrieval>(`/papers/${encodeURIComponent(paperId)}/retrieval/rebuild`, json('POST', { request_id: crypto.randomUUID() })),
    onSuccess: (data) => client.setQueryData(queryKeys.retrieval.paper(paperId), data),
  })
}
