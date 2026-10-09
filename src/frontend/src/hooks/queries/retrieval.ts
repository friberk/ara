import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { EmbeddingProfilePage, RetrievalSettings } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

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
