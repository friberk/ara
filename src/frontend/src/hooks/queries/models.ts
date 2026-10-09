import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { Collection, GenerationSettings, Model, Settings, SettingsUpdate } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: ({ signal }) => api<Collection<Model>>('/models', { signal }),
    staleTime: 10_000,
    refetchOnWindowFocus: 'always',
    refetchInterval: (current) => current.state.data?.items.some((model) => model.installation && (['queued', 'downloading', 'pausing', 'verifying', 'deleting'].includes(model.installation.state) || (model.installation.state === 'ready' && model.unavailable_code === 'LOCAL_MODEL_REVALIDATION_REQUIRED'))) ? 2000 : 30_000,
  })
}

export function useSavedSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: ({ signal }) => api<Settings>('/settings', { signal }) })
}

export function useSaveDefaults() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (value: GenerationSettings) => api<Settings>('/settings', json('PUT', { default_model: value.model, reasoning_effort: value.reasoning_effort } satisfies SettingsUpdate)),
    onSuccess: (data) => client.setQueryData(queryKeys.settings, data),
  })
}

/** Only chat models generate; search and ranking models serve retrieval. The schema defaults a missing kind to chat. */
export function isChatModel(model: Model) { return (model.kind ?? 'chat') === 'chat' }

export type Purpose = 'chat' | 'summary'
/** Whether a model can serve this kind of generation at all, independent of the chosen effort. */
export function modelSupports(model: Model | undefined, purpose?: Purpose) {
  if (!model || model.status === 'unavailable') return false
  if (purpose === 'chat') return model.supports_streaming
  if (purpose === 'summary') return model.supports_structured_output
  return true
}
export function unavailableReason(model: Model, purpose?: Purpose) {
  if (model.status === 'unavailable') return model.unavailable_reason ?? (model.installation ? 'Download weights in Settings to use this model.' : 'Not configured on the server')
  if (purpose === 'chat' && !model.supports_streaming) return 'Cannot stream answers'
  if (purpose === 'summary' && !model.supports_structured_output) return 'Cannot write summaries'
  return null
}
