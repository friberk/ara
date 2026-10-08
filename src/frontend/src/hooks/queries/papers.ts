import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { api, json, query } from '@/api/client'
import type { Collection, Paper, PaperPatch, SavePaper, SearchHit, SearchPage } from '@/api/types'
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

const normalizeDoi = (doi: string | null | undefined) => doi?.trim().toLowerCase().replace(/^https?:\/\/(dx\.)?doi\.org\//, '') || null

/** Whether a search hit is the work that was just saved: same provider record, or same DOI (the server's identity rules). */
export function isSameWork(hit: SearchHit, paper: Paper) {
  const doi = normalizeDoi(paper.doi)
  return paper.sources.some((source) => source.provider === hit.provider && source.external_id === hit.external_id) || (!!doi && normalizeDoi(hit.doi) === doi)
}

export function useSavePaper() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SavePaper) => api<Paper>('/papers', json('POST', body)),
    onSuccess: (paper) => {
      client.setQueryData(queryKeys.papers.detail(paper.id), paper)
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      // Mark matching hits saved in place: re-fetching every loaded page would hit provider rate limits.
      client.setQueriesData<InfiniteData<SearchPage>>({ queryKey: ['search'] }, (data) => data && {
        ...data,
        pages: data.pages.map((page) => ({ ...page, items: page.items.map((hit) => isSameWork(hit, paper) ? { ...hit, saved_paper_id: paper.id } : hit) })),
      })
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
