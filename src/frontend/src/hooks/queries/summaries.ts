import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { GenerationInput, GenerationSettings, SummaryAccepted, SummaryPage } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export function useSummaries(paperId: string) {
  return useQuery({ queryKey: queryKeys.summaries(paperId), queryFn: ({ signal }) => api<SummaryPage>(`/papers/${paperId}/summaries`, { signal }) })
}

/** Each request gets a fresh UUID: a new summary is a deliberate, paid generation. */
export function useGenerateSummary(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (settings: GenerationSettings) => api<SummaryAccepted>(`/papers/${paperId}/summaries`, json('POST', { ...settings, request_id: crypto.randomUUID() } satisfies GenerationInput)),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.jobs.all }),
  })
}
