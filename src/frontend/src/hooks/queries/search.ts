import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiVoid, json, query, remove } from '@/api/client'
import type { Collection, Provider, SearchHistoryItem, SearchHit, SearchPage } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export type SearchParams = { q: string; provider: Provider }

export function useSearch(params: SearchParams | null) {
  return useInfiniteQuery({
    queryKey: queryKeys.search(params ?? { q: '', provider: 'openalex' }),
    queryFn: ({ pageParam, signal }) => api<SearchPage>(`/search${query({ q: params?.q, provider: params?.provider, limit: 20, cursor: pageParam })}`, { signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: !!params,
    retry: false,
    staleTime: 60_000,
  })
}

/** Flattens pages and drops repeats the provider returns across cursors. */
export function uniqueHits(pages: SearchPage[] | undefined): SearchHit[] {
  const seen = new Set<string>()
  const hits: SearchHit[] = []
  for (const item of pages?.flatMap((page) => page.items) ?? []) {
    const key = `${item.provider}:${item.external_id}`
    if (!seen.has(key)) { seen.add(key); hits.push(item) }
  }
  return hits
}

export function useSearchHistory(limit = 20) {
  return useQuery({
    queryKey: queryKeys.searchHistory.list(limit),
    queryFn: ({ signal }) => api<Collection<SearchHistoryItem>>(`/search-history${query({ limit })}`, { signal }),
    retry: false,
  })
}

export function useRecordSearch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (params: SearchParams) => api<SearchHistoryItem>('/search-history', json('POST', { provider: params.provider, query: params.q })),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.searchHistory.all }),
  })
}

export function useDeleteSearch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiVoid(`/search-history/${id}`, remove),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.searchHistory.all }),
  })
}

export function useClearSearchHistory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiVoid('/search-history', remove),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.searchHistory.all }),
  })
}
