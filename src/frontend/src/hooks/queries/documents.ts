import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiVoid, remove } from '@/api/client'
import type { Citation, DocumentDetail, PdfRemovalPreview } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

/** The complete stored chunk behind a citation, verified to be the one that was cited. */
export function useCitationSource(citation: Citation, enabled = true) {
  return useQuery({
    queryKey: queryKeys.citation(citation.document_id, citation.chunk_id),
    queryFn: async ({ signal }) => {
      const source = await api<Citation>(`/documents/${encodeURIComponent(citation.document_id)}/chunks/${encodeURIComponent(citation.chunk_id)}`, { signal })
      if (source.document_id !== citation.document_id || source.chunk_id !== citation.chunk_id || source.page !== citation.page) throw new Error('This citation could not be matched to its source.')
      return source
    },
    enabled,
    staleTime: Infinity,
  })
}

/** One PDF's file facts for the reader's menu: name, pages, size and where it came from (ARA-097). */
export function useDocument(documentId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.documents.detail(documentId ?? ''),
    queryFn: ({ signal }) => api<DocumentDetail>(`/documents/${encodeURIComponent(documentId ?? '')}`, { signal }),
    enabled: !!documentId,
    staleTime: Infinity,
  })
}

/** What removing the paper's PDF changes, read afresh each time the dialog opens (ARA-097). */
export function usePdfRemovalPreview(paperId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.pdfRemovalPreview(paperId),
    queryFn: ({ signal }) => api<PdfRemovalPreview>(`/papers/${encodeURIComponent(paperId)}/pdf/removal-preview`, { signal }),
    enabled,
    staleTime: 0,
    gcTime: 0,
  })
}

/**
 * Removes the paper's PDF and its earlier versions (ARA-097). The paper, its chats and their saved answers stay; the
 * reader returns to its upload state when the paper is read again.
 */
export function useRemovePdf(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiVoid(`/papers/${encodeURIComponent(paperId)}/pdf`, remove),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      void client.invalidateQueries({ queryKey: queryKeys.chats.all })
      void client.invalidateQueries({ queryKey: queryKeys.jobs.all })
      void client.invalidateQueries({ queryKey: queryKeys.fulltext(paperId) })
      void client.invalidateQueries({ queryKey: queryKeys.summaries(paperId) })
      void client.invalidateQueries({ queryKey: queryKeys.retrieval.paper(paperId) })
      void client.invalidateQueries({ queryKey: queryKeys.documents.all })
    },
  })
}
