import { useId, useState } from 'react'
import { Check } from 'lucide-react'
import type { GenerationSettings, Model, Settings } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { effortLabel } from '@/components/composer/effort'
import { normaliseSettings, reasoningControls } from '@/components/composer/reasoning'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useOpenModels, withoutOpenModels } from '@/hooks/queries/features'
import { isChatModel, useModels, useSaveDefaults, useSavedSettings } from '@/hooks/queries/models'
import { formatTokens } from '@/lib/usage-format'
import { cn } from '@/lib/utils'
import { ChoiceList, ChoiceRow, SettingsSection } from './parts'
import { segmentedGroup, segmentedItem } from './segmented'

const price = (usd: number) => `$${usd.toFixed(2)}`

/** Why a model cannot be chosen, in words that say how to fix it. */
function unavailableNote(model: Model) {
  if (model.unavailable_reason) return model.unavailable_reason
  if (model.installation) return 'Download it under Open models to use it.'
  return model.provider === 'ollama' ? 'Not available on the server right now.' : 'Add an OpenAI API key to the server, then restart it.'
}

/** What a model is for, what it costs and how much it reads; limits are named only when a model has them. */
function ModelDetails({ model }: { model: Model }) {
  const limits = [!model.supports_streaming && 'Shows each answer only once it is complete.', !model.supports_structured_output && 'Can’t write paper summaries.'].filter(Boolean)
  const purpose = model.description ?? (model.provider === 'ollama' ? 'Runs on this server, with no per-token cost.' : null)
  return (
    <>
      {(purpose || limits.length > 0) && <span>{[purpose, ...limits].filter(Boolean).join(' ')}</span>}{' '}
      {model.status === 'unavailable' ? <span>{unavailableNote(model)}</span> : (
        // Spaces between the facts keep them apart when a screen reader reads the row's description as one line.
        // Fixed columns from the small breakpoint keep the figures in line from one model to the next.
        <span className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums sm:grid sm:grid-cols-[6rem_7.5rem_1fr] sm:gap-x-2">
          {model.input_price_per_million != null && <span>Input <span className="text-foreground">{price(model.input_price_per_million)}</span></span>}{' '}
          {model.output_price_per_million != null && <span>Output <span className="text-foreground">{price(model.output_price_per_million)}</span></span>}{' '}
          <span>Context <span className="text-foreground">{formatTokens(model.context_window)} tokens</span></span>
        </span>
      )}
    </>
  )
}

function DefaultNote() {
  return <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-foreground"><Check aria-hidden="true" className="size-3.5" />Default</span>
}

/**
 * The model and reasoning new chats start with. A choice saves as soon as it is made; while it saves it shows as
 * chosen, and a failed save falls back to the stored default. Shown values are normalised for this model without
 * saving, so an older stored preference is displayed but never rewritten on its own.
 */
function ModelDefaults({ models, saved }: { models: Model[]; saved: Settings }) {
  const modelHeading = useId()
  const reasoningHeading = useId()
  const save = useSaveDefaults()
  const [changed, setChanged] = useState<'model' | 'reasoning'>('model')
  const stored: GenerationSettings = { model: saved.default_model, reasoning_effort: saved.reasoning_effort }
  const shown = normaliseSettings(models, save.isPending && save.variables ? save.variables : stored)
  const selected = models.find((model) => model.key === shown.model)
  const controls = reasoningControls(selected)
  const commit = (next: GenerationSettings, field: 'model' | 'reasoning') => { setChanged(field); save.mutate(normaliseSettings(models, next)) }
  const status = (field: 'model' | 'reasoning') => (changed === field && save.isSuccess ? 'Saved' : '')
  return (
    <>
      <SettingsSection
        headingId={modelHeading}
        title="Default model"
        status={status('model')}
        description={<p>New chats start with this model, and paper summaries use it. Any chat can switch to another model from the menu next to the send button.</p>}
      >
        <ChoiceList labelledBy={modelHeading}>
          {models.map((model) => (
            <ChoiceRow key={model.key} name={modelHeading} value={model.key} checked={shown.model === model.key} disabled={model.status === 'unavailable'} onSelect={() => commit({ model: model.key, reasoning_effort: shown.reasoning_effort }, 'model')} title={model.display_name} note={shown.model === model.key && <DefaultNote />}>
              <ModelDetails model={model} />
            </ChoiceRow>
          ))}
        </ChoiceList>
        <p className="text-xs text-muted-foreground">Prices are in US dollars per million tokens. Context is how much text a model can read at once.</p>
        {changed === 'model' && <ErrorNotice error={save.error} />}
      </SettingsSection>
      <SettingsSection
        headingId={reasoningHeading}
        title="Reasoning"
        status={status('reasoning')}
        description={<p>How long the model thinks before it answers. More reasoning helps with hard questions, but answers take longer and cost more.</p>}
        control={controls.kind === 'boolean' && <Switch aria-labelledby={reasoningHeading} checked={shown.reasoning_effort === 'on'} onCheckedChange={(enabled) => commit({ model: shown.model, reasoning_effort: enabled ? 'on' : 'none' }, 'reasoning')} className="mt-0.5" />}
      >
        {controls.kind === 'levels' && controls.options.length > 0 && (
          <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-labelledby={reasoningHeading} value={shown.reasoning_effort} onValueChange={(value) => { if (value) commit({ model: shown.model, reasoning_effort: value }, 'reasoning') }} className={cn(segmentedGroup, controls.options.length > 4 && 'max-sm:grid max-sm:w-full max-sm:grid-cols-3')}>
            {controls.options.map((effort) => <ToggleGroupItem key={effort} value={effort} className={segmentedItem}>{effortLabel(effort)}</ToggleGroupItem>)}
          </ToggleGroup>
        )}
        {controls.kind === 'controlled' && (
          <p className="text-sm text-muted-foreground">{selected?.status === 'unavailable' ? unavailableNote(selected) : selected ? 'This model decides how much to reason.' : 'Choose a model to see its reasoning options.'}</p>
        )}
        {changed === 'reasoning' && <ErrorNotice error={save.error} />}
      </SettingsSection>
    </>
  )
}

/** The Models category: the default model and reasoning for new chats. */
export function ModelSettings() {
  const models = useModels()
  const saved = useSavedSettings()
  const openModels = useOpenModels()
  // A saved local default is listed, reported unavailable by the server; other local models stay hidden while off.
  const chatModels = models.data && withoutOpenModels(models.data.items.filter(isChatModel), openModels, saved.data?.default_model)
  const error = models.error ?? saved.error
  if (error) return <ErrorNotice error={error} retry={() => { void models.refetch(); void saved.refetch() }} className="mt-1" />
  if (!chatModels || !saved.data) {
    return <div role="status" className="grid gap-3 pt-1"><span className="sr-only">Loading models…</span><Skeleton className="h-4 w-40" /><Skeleton className="h-20 w-full rounded-xl" /><Skeleton className="h-20 w-full rounded-xl" /></div>
  }
  if (!chatModels.length) return <EmptyState title="No models are set up">The server lists no models. Check its configuration, then reopen Settings.</EmptyState>
  return <ModelDefaults models={chatModels} saved={saved.data} />
}
