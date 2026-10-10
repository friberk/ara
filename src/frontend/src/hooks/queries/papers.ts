import { useInfiniteQuery, useMutation, useQueries, useQuery, useQueryClient, type InfiniteData, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { api, ApiError, apiVoid, json, query, remove } from '@/api/client'
import type { Collection, DeletedPapers, DeletionPreview, JobView, Paper, PaperPatch, SavePaper, SearchHit, SearchPage } from '@/api/types'
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
export function paperQuery(id: string | undefined) {
  return {
    queryKey: queryKeys.papers.detail(id ?? ''),
    queryFn: ({ signal }: { signal: AbortSignal }) => api<Paper>(`/papers/${encodeURIComponent(id ?? '')}`, { signal }),
    enabled: !!id,
    // An upload waiting for a library-match choice is not being read, so it is not polled (ARA-086).
    refetchInterval: (current: { state: { data?: Paper } }) => current.state.data?.document_status === 'processing' && !current.state.data.upload_match ? 1500 : false,
  }
}

export function usePaper(id: string | undefined) {
  return useQuery(paperQuery(id))
}

const loadedPapers = (results: { data?: Paper }[]) => results.flatMap((result) => (result.data ? [result.data] : []))

/** The loaded papers among several, such as those an answer cites (ARA-088). */
export function usePaperList(ids: readonly string[]) {
  return useQueries({ queries: ids.map((id) => paperQuery(id)), combine: loadedPapers })
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

/** What deleting these papers removes (ARA-095). Read afresh each time the dialog opens, since chats and jobs change. */
export function useDeletionPreview(ids: readonly string[], enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.deletionPreview(ids),
    queryFn: ({ signal }) => ids.length === 1
      ? api<DeletionPreview>(`/papers/${encodeURIComponent(ids[0]!)}/deletion-preview`, { signal })
      : api<DeletionPreview>('/papers/deletion-preview', { ...json('POST', { paper_ids: ids }), signal }),
    enabled: enabled && ids.length > 0,
    staleTime: 0,
    gcTime: 0,
  })
}

/** Whether a query belongs to one of the deleted papers, so reading it again would answer 404. */
function aboutDeleted(key: QueryKey, gone: ReadonlySet<string>) {
  const [root, part, value] = key
  const filters = typeof value === 'object' && value !== null ? value as { paperId?: unknown } : {}
  if (root === 'papers' && part === 'detail') return gone.has(String(value))
  if (root === 'summaries' || root === 'fulltext') return gone.has(String(part))
  if (root === 'retrieval' && part === 'paper') return gone.has(String(value))
  if ((root === 'jobs' || root === 'chats') && part === 'list') return gone.has(String(filters.paperId))
  return false
}

function forgetPapers(client: QueryClient, ids: readonly string[]) {
  const gone = new Set(ids)
  // Rows leave every loaded list at once; the lists are then read again.
  client.setQueriesData<InfiniteData<Collection<Paper>>>({ queryKey: ['papers', 'list'] }, (data) => data && {
    ...data,
    pages: data.pages.map((page) => ({ ...page, items: page.items.filter((paper) => !gone.has(paper.id)) })),
  })
  // A page still open on a deleted paper keeps its data until it navigates away.
  client.removeQueries({ predicate: (item) => aboutDeleted(item.queryKey, gone), type: 'inactive' })
  void client.invalidateQueries({ predicate: (item) => ['papers', 'chats', 'jobs'].includes(String(item.queryKey[0])) && !aboutDeleted(item.queryKey, gone) })
  // Answers that cited a deleted paper no longer name it; open chats pick that up when next read.
  void client.invalidateQueries({ queryKey: ['messages'], refetchType: 'none' })
}

/**
 * Deletes papers and returns the IDs that are gone; one already deleted counts as deleted.
 * One paper uses DELETE /papers/{id}; several are deleted together in one request.
 */
export function useDeletePapers() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (ids: readonly string[]): Promise<string[]> => {
      if (ids.length === 1) {
        try { await apiVoid(`/papers/${encodeURIComponent(ids[0]!)}`, remove) } catch (error) { if (!(error instanceof ApiError && error.status === 404)) throw error }
        return [...ids]
      }
      const result = await api<DeletedPapers>('/papers/delete', json('POST', { paper_ids: ids }))
      return [...result.deleted, ...result.missing]
    },
    onSuccess: (ids) => forgetPapers(client, ids),
  })
}

/** Looks the paper up again in the metadata source; fields the user edited stay (ARA-095). */
export function useLookUpAgain(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<JobView>(`/papers/${encodeURIComponent(paperId)}/metadata-lookup`, { method: 'POST' }),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.jobs.all }),
  })
}
