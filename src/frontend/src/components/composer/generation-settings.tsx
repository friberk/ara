import { createContext, useContext, useMemo, useState } from 'react'
import type { GenerationSettings, Model } from '@/api/types'
import { modelSupports, useModels, useSavedSettings, type Purpose } from '@/hooks/queries/models'

type GenerationSettingsValue = {
  /** Effective selection: the session choice, else the saved default, normalised to an effort the model supports. */
  settings: GenerationSettings
  setSettings: (next: GenerationSettings) => void
  models: Model[]
  selectedModel: Model | undefined
  savedDefaults: GenerationSettings | null
  loading: boolean
  error: unknown
  retry: () => void
  /** True when the selected model and effort can serve this kind of generation. */
  usableFor: (purpose: Purpose) => boolean
}

const GenerationSettingsContext = createContext<GenerationSettingsValue | null>(null)

function normalise(models: Model[], value: GenerationSettings): GenerationSettings {
  const model = models.find((item) => item.key === value.model)
  if (!model) return value
  return model.reasoning_efforts.includes(value.reasoning_effort) ? value : { model: model.key, reasoning_effort: model.reasoning_efforts[0] ?? 'none' }
}

export function GenerationSettingsProvider({ children }: { children: React.ReactNode }) {
  const models = useModels()
  const saved = useSavedSettings()
  const [choice, setChoice] = useState<GenerationSettings | null>(null)
  const value = useMemo<GenerationSettingsValue>(() => {
    const items = models.data?.items ?? []
    const savedDefaults = saved.data?.default_model ? { model: saved.data.default_model, reasoning_effort: saved.data.reasoning_effort } : null
    const fallback = items.find((model) => model.status !== 'unavailable')
    const base = choice ?? savedDefaults ?? (fallback ? { model: fallback.key, reasoning_effort: fallback.reasoning_efforts[0] ?? 'none' } : { model: '', reasoning_effort: 'none' })
    const settings = normalise(items, base)
    const selectedModel = items.find((model) => model.key === settings.model)
    return {
      settings,
      setSettings: (next) => setChoice(normalise(items, next)),
      models: items,
      selectedModel,
      savedDefaults,
      loading: models.isPending || saved.isPending,
      error: models.error ?? saved.error,
      retry: () => { void models.refetch(); void saved.refetch() },
      usableFor: (purpose) => modelSupports(selectedModel, purpose) && !!selectedModel?.reasoning_efforts.includes(settings.reasoning_effort),
    }
  }, [choice, models, saved])
  return <GenerationSettingsContext.Provider value={value}>{children}</GenerationSettingsContext.Provider>
}

export function useGenerationSettings() {
  const context = useContext(GenerationSettingsContext)
  if (!context) throw new Error('useGenerationSettings must be used within GenerationSettingsProvider.')
  return context
}
