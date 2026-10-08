import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { Collection, GenerationSettings, Model, Settings } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export function useModels() {
  return useQuery({ queryKey: queryKeys.models, queryFn: ({ signal }) => api<Collection<Model>>('/models', { signal }), staleTime: 5 * 60_000 })
}

export function useSavedSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: ({ signal }) => api<Settings>('/settings', { signal }) })
}

export function useSaveDefaults() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (value: GenerationSettings) => api<Settings>('/settings', json('PUT', { default_model: value.model, reasoning_effort: value.reasoning_effort } satisfies Settings)),
    onSuccess: (data) => client.setQueryData(queryKeys.settings, data),
  })
}

export type Purpose = 'chat' | 'summary'
/** Whether a model can serve this kind of generation at all, independent of the chosen effort. */
export function modelSupports(model: Model | undefined, purpose?: Purpose) {
  if (!model || model.status === 'unavailable') return false
  if (purpose === 'chat') return model.supports_streaming
  if (purpose === 'summary') return model.supports_structured_output
  return true
}
export function unavailableReason(model: Model, purpose?: Purpose) {
  if (model.status === 'unavailable') return 'Not configured on the server'
  if (purpose === 'chat' && !model.supports_streaming) return 'Cannot stream answers'
  if (purpose === 'summary' && !model.supports_structured_output) return 'Cannot write summaries'
  return null
}
