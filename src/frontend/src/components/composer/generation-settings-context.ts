import { createContext, useContext } from 'react'
import type { GenerationSettings, Model } from '@/api/types'
import type { Purpose } from '@/hooks/queries/models'

export type GenerationSettingsValue = {
  /** Effective selection: the session choice, else the saved default, normalised to an effort the model supports. */
  settings: GenerationSettings
  setSettings: (next: GenerationSettings) => void
  models: Model[]
  selectedModel: Model | undefined
  loading: boolean
  error: unknown
  retry: () => void
  /** True when the selected model and effort can serve this kind of generation. */
  usableFor: (purpose: Purpose) => boolean
}

export const GenerationSettingsContext = createContext<GenerationSettingsValue | null>(null)

export function useGenerationSettings() {
  const context = useContext(GenerationSettingsContext)
  if (!context) throw new Error('useGenerationSettings must be used within GenerationSettingsProvider.')
  return context
}
