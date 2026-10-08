import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json, query } from '@/api/client'
import type { Collection, Paper, PaperPatch, SavePaper } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export const PAPER_PAGE_SIZE = 20

/** Library papers, newest first, filtered by title. */
export function usePapers(filter = '', options: { pageSize?: number; enabled?: boolean } = {}) {
  const pageSize = options.pageSize ?? PAPER_PAGE_SIZE
  return useInfiniteQuery({
    queryKey: [...queryKeys.papers.list(filter), pageSize],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api<Collection<Paper>>(`/papers${query({ q: filter, limit: pageSize, offset: pageParam })}`, { signal }),
    getNextPageParam: (page, _all, offset) => page.items.length === pageSize ? offset + pageSize : undefined,
    enabled: options.enabled ?? true,
  })
}

/** One paper; polls while its PDF is processing so readiness appears without a reload. */
export function usePaper(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.papers.detail(id ?? ''),
    queryFn: ({ signal }) => api<Paper>(`/papers/${encodeURIComponent(id ?? '')}`, { signal }),
    enabled: !!id,
    refetchInterval: (current) => current.state.data?.document_status === 'processing' ? 1500 : false,
  })
}

export function useSavePaper() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SavePaper) => api<Paper>('/papers', json('POST', body)),
    onSuccess: (paper) => {
      client.setQueryData(queryKeys.papers.detail(paper.id), paper)
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      void client.invalidateQueries({ queryKey: ['search'] })
    },
  })
}

export function usePatchPaper(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: PaperPatch) => api<Paper>(`/papers/${paperId}`, json('PATCH', patch)),
    onSuccess: (paper) => {
      client.setQueryData(queryKeys.papers.detail(paper.id), paper)
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      void client.invalidateQueries({ queryKey: queryKeys.chats.all })
    },
  })
}
