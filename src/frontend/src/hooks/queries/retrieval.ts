import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { ChatMemoryState, EmbeddingProfilePage, PaperRetrieval, ReindexEstimate, RetrievalIndex, RetrievalSettings } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export function isBuilding(index: RetrievalIndex) { return index.state === 'queued' || index.state === 'embedding' }

/** Search models the library can be embedded with, with install status and price. */
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
      // The profile page reports the model the library follows, and every paper re-embeds with it.
      void client.invalidateQueries({ queryKey: queryKeys.retrieval.profiles })
      void client.invalidateQueries({ queryKey: ['retrieval', 'paper'] })
    },
  })
}

/** The library model and the state of a paper's indexes; polls while any index is building. */
export function usePaperRetrieval(paperId: string) {
  return useQuery({
    queryKey: queryKeys.retrieval.paper(paperId),
    queryFn: ({ signal }) => api<PaperRetrieval>(`/papers/${encodeURIComponent(paperId)}/retrieval`, { signal }),
    refetchInterval: (current) => current.state.data?.indexes.some(isBuilding) ? 1500 : false,
  })
}

/** What switching the library to `profile` would re-embed: papers, tokens and an estimated cost. Always read fresh. */
export function useReindexEstimate(profile: string | null) {
  return useQuery({
    queryKey: queryKeys.retrieval.estimate(profile ?? ''),
    queryFn: ({ signal }) => api<ReindexEstimate>(`/retrieval/reindex-estimate?profile=${encodeURIComponent(profile ?? '')}`, { signal }),
    enabled: profile !== null,
    gcTime: 0,
  })
}

/** A chat's running summary of earlier messages, if it has one. The chat stream refreshes it after each answer. */
export function useChatMemory(chatId: string) {
  return useQuery({ queryKey: queryKeys.retrieval.memory(chatId), queryFn: ({ signal }) => api<ChatMemoryState>(`/chats/${encodeURIComponent(chatId)}/memory`, { signal }) })
}

export function useRebuildPaperRetrieval(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<PaperRetrieval>(`/papers/${encodeURIComponent(paperId)}/retrieval/rebuild`, json('POST', { request_id: crypto.randomUUID() })),
    onSuccess: (data) => client.setQueryData(queryKeys.retrieval.paper(paperId), data),
  })
}
