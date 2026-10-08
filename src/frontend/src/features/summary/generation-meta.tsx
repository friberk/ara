import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { cn } from '@/lib/utils'
import { effortText } from './format'

/**
 * The model and effort a response was generated with, as stored on it, never the current selection.
 * Known models show their display name; a model the server no longer lists keeps its exact ID.
 */
export function GenerationMeta({ model, effort, className }: { model: string | null; effort: string | null; className?: string }) {
  const { models } = useGenerationSettings()
  if (!model) return null
  const known = models.find((item) => item.key === model)
  return (
    <>
      <span title={model} className={cn(!known && 'font-mono', className)}>{known?.display_name ?? model}</span>
      {effort && <span className={className}>{effortText(effort)}</span>}
    </>
  )
}
