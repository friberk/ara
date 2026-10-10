import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Features } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

/** Server features the UI adapts to. They change only when the server restarts. */
export function useFeatures() {
  return useQuery({ queryKey: queryKeys.features, queryFn: ({ signal }) => api<Features>('/features', { signal }), staleTime: Infinity })
}

/** Open (local) models are experimental and frozen: nothing of them shows unless the server reports them on (ARA-090). */
export function useOpenModels() {
  return useFeatures().data?.open_models === true
}

/**
 * A model or profile list without local entries while open models are off. `keep` is a saved choice, which the
 * server still reports so it can be shown as unavailable instead of silently replaced.
 */
export function withoutOpenModels<T extends { key: string; provider: string }>(items: T[], openModels: boolean, keep?: string | null) {
  return openModels ? items : items.filter((item) => item.provider !== 'ollama' || item.key === keep)
}
