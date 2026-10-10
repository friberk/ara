import { useMemo, useState } from 'react'
import type { GenerationSettings } from '@/api/types'
import { useOpenModels, withoutOpenModels } from '@/hooks/queries/features'
import { isChatModel, modelSupports, useModels, useSavedSettings } from '@/hooks/queries/models'
import { GenerationSettingsContext, type GenerationSettingsValue } from './generation-settings-context'
import { normaliseSettings } from './reasoning'

export function GenerationSettingsProvider({ children }: { children: React.ReactNode }) {
  const models = useModels()
  const saved = useSavedSettings()
  const openModels = useOpenModels()
  const [choice, setChoice] = useState<GenerationSettings | null>(null)
  const value = useMemo<GenerationSettingsValue>(() => {
    // A saved local default stays known, as the server reports it unavailable, so nothing switches to a paid model.
    const items = withoutOpenModels((models.data?.items ?? []).filter(isChatModel), openModels, saved.data?.default_model)
    const savedPreference = saved.data?.default_model ? { model: saved.data.default_model, reasoning_effort: saved.data.reasoning_effort } : null
    const savedDefaults = savedPreference ? normaliseSettings(items, savedPreference) : null
    // Missing defaults may choose a first model; a failed settings request is not evidence
    // that there is no saved local default. Keep automatic paid selection blocked.
    const fallback = saved.isSuccess ? items.find((model) => model.status !== 'unavailable') : undefined
    const base = choice ?? savedPreference ?? (fallback ? { model: fallback.key, reasoning_effort: fallback.reasoning_efforts[0] ?? 'none' } : { model: '', reasoning_effort: 'none' })
    const settings = normaliseSettings(items, base)
    const selectedModel = items.find((model) => model.key === settings.model)
    return {
      settings,
      setSettings: (next) => setChoice(normaliseSettings(items, next)),
      models: items,
      selectedModel,
      savedDefaults,
      loading: models.isPending || saved.isPending,
      error: models.error ?? saved.error,
      retry: () => { void models.refetch(); void saved.refetch() },
      usableFor: (purpose) => modelSupports(selectedModel, purpose) && !!selectedModel?.reasoning_efforts.includes(settings.reasoning_effort),
    }
  }, [choice, models, saved, openModels])
  return <GenerationSettingsContext.Provider value={value}>{children}</GenerationSettingsContext.Provider>
}
