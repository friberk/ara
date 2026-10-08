import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Citation } from '@/api/types'
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
