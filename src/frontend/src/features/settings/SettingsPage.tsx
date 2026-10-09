import { useId, useState } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'
import type { GenerationSettings, Model, Settings } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Toggle } from '@/components/ui/toggle'
import { effortLabel } from '@/components/composer/effort'
import { normaliseSettings, reasoningControls } from '@/components/composer/reasoning'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useTheme } from '@/components/theme/theme-context'
import { isChatModel, unavailableReason, useModels, useSaveDefaults, useSavedSettings } from '@/hooks/queries/models'
import { cn } from '@/lib/utils'
import { segmentedGroup, segmentedItem } from './segmented'
import { LocalModels } from './LocalModels'
import { RetrievalSettingsSection } from './RetrievalSettingsSection'
import { MetadataSettingsSection } from './MetadataSettingsSection'

const statusBadges: Record<Model['status'], { label: string; tone: string }> = {
  available: { label: 'Available', tone: 'bg-success-muted text-success' },
  configured: { label: 'Configured', tone: '' },
  unavailable: { label: 'Unavailable', tone: 'bg-muted text-muted-foreground' },
}
const themes = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const

function capabilityNote(model: Model) {
  if (model.status === 'unavailable') return model.unavailable_reason ?? (model.installation ? 'Download weights in Local models below to enable this model.' : 'Not configured on the server. Ask the server administrator to enable access.')
  if (model.supports_streaming && model.supports_structured_output) return 'Streams answers and writes summaries.'
  return [model.supports_streaming ? 'Streams answers.' : 'Cannot stream answers.', model.supports_structured_output ? 'Writes summaries.' : 'Cannot write summaries.'].join(' ')
}

function ModelOption({ model, name, checked, onSelect }: { model: Model; name: string; checked: boolean; onSelect: () => void }) {
  const id = useId()
  const disabled = model.status === 'unavailable'
  const badge = statusBadges[model.status]
  return (
    <label htmlFor={`${id}-radio`} className={cn('flex gap-3 px-4 py-3.5 transition-colors', disabled ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-muted/50', checked && 'bg-muted/60 hover:bg-muted/60')}>
      <input id={`${id}-radio`} type="radio" name={name} value={model.key} checked={checked} disabled={disabled} onChange={onSelect} aria-labelledby={`${id}-name`} aria-describedby={`${id}-details`} className="mt-0.5 size-4 shrink-0 accent-foreground disabled:cursor-not-allowed" />
      <span className={cn('grid min-w-0 flex-1 gap-1', disabled && 'opacity-60')}>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span id={`${id}-name`} className="text-sm font-medium">{model.display_name}</span>
          <Badge variant="secondary" className={cn('font-normal', badge.tone)}>{badge.label}</Badge>
        </span>
        <span id={`${id}-details`} className="grid gap-0.5 text-xs text-muted-foreground">
          <span className="font-mono break-all">{model.model_id}</span>
          <span>{capabilityNote(model)}</span>
        </span>
      </span>
    </label>
  )
}

function ModelDefaults({ models, saved, labelledBy }: { models: Model[]; saved: Settings; labelledBy: string }) {
  const effortId = useId()
  const memoryId = useId()
  const save = useSaveDefaults()
  const [preference, setPreference] = useState<GenerationSettings>(() => ({ model: saved.default_model, reasoning_effort: saved.reasoning_effort }))
  const [memory, setMemory] = useState(saved.memory_model)
  const draft = normaliseSettings(models, preference)
  const savedDefault = normaliseSettings(models, { model: saved.default_model, reasoning_effort: saved.reasoning_effort })
  const selected = models.find((model) => model.key === draft.model)
  const controls = reasoningControls(selected)
  // The server accepts any hosted chat model from its catalog; local chats always use their own model.
  const hosted = models.filter((model) => model.provider !== 'ollama')
  const valid = !!selected && selected.status !== 'unavailable' && selected.reasoning_efforts.includes(draft.reasoning_effort)
  const dirty = draft.model !== savedDefault.model || draft.reasoning_effort !== savedDefault.reasoning_effort || memory !== saved.memory_model
  const change = (next: GenerationSettings) => { save.reset(); setPreference(normaliseSettings(models, next)) }
  return (
    <form className="grid gap-8" onSubmit={(event) => { event.preventDefault(); if (valid && dirty) save.mutate({ ...draft, memory_model: memory }) }}>
      <div role="radiogroup" aria-labelledby={labelledBy} className="divide-y overflow-hidden rounded-xl border">
        {models.map((model) => <ModelOption key={model.key} model={model} name={labelledBy} checked={draft.model === model.key} onSelect={() => change({ model: model.key, reasoning_effort: draft.reasoning_effort })} />)}
      </div>
      <div className="grid gap-3">
        <div className="grid gap-1">
          <h3 id={effortId} className="text-sm font-medium">{controls.kind === 'levels' ? 'Reasoning effort' : 'Reasoning'}</h3>
          {controls.kind === 'levels' && <p className="text-sm text-muted-foreground">More effort can help with harder questions, but answers take longer.</p>}
        </div>
        {controls.kind === 'levels' && controls.options.length ? (
          <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-labelledby={effortId} value={draft.reasoning_effort} onValueChange={(value) => { if (value) change({ model: draft.model, reasoning_effort: value }) }} className={segmentedGroup}>
            {controls.options.map((effort) => <ToggleGroupItem key={effort} value={effort} className={segmentedItem}>{effortLabel(effort)}</ToggleGroupItem>)}
          </ToggleGroup>
        ) : controls.kind === 'boolean' ? (
          <Toggle variant="outline" size="sm" aria-labelledby={effortId} pressed={draft.reasoning_effort === 'on'} onPressedChange={(enabled) => change({ model: draft.model, reasoning_effort: enabled ? 'on' : 'none' })} className="w-fit">{draft.reasoning_effort === 'on' ? 'Enabled' : 'Disabled'}</Toggle>
        ) : (
          <p className="text-sm text-muted-foreground">{selected?.status === 'unavailable' ? unavailableReason(selected) : selected ? 'Reasoning is controlled by this model.' : 'Choose a model to see its reasoning options.'}</p>
        )}
      </div>
      {hosted.length > 0 && (
        <div className="grid gap-3">
          <div className="grid gap-1">
            <h3 id={memoryId} className="text-sm font-medium">Model for summaries and follow-up questions</h3>
            <p className="text-sm text-pretty text-muted-foreground">Hosted chats use it, at its lowest reasoning effort, to summarize earlier messages and to turn follow-up questions into searches. Local chats use their own model.</p>
          </div>
          <div role="radiogroup" aria-labelledby={memoryId} className="divide-y overflow-hidden rounded-xl border">
            {hosted.map((model) => <ModelOption key={model.key} model={model} name={memoryId} checked={memory === model.key} onSelect={() => { save.reset(); setMemory(model.key) }} />)}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" disabled={!valid || !dirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save defaults'}</Button>
        <p role="status" className="text-sm text-muted-foreground">{save.isSuccess && !dirty ? 'Model defaults saved.' : ''}</p>
      </div>
      <ErrorNotice error={save.error} />
    </form>
  )
}

function Appearance() {
  const { theme, setTheme } = useTheme()
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="grid gap-4">
      <div className="grid gap-1">
        <h2 id={headingId} className="text-base font-semibold tracking-tight">Appearance</h2>
        <p className="text-sm text-muted-foreground">System follows your device and switches with it.</p>
      </div>
      <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-label="Theme" value={theme} onValueChange={(value) => { if (value) setTheme(value) }} className={segmentedGroup}>
        {themes.map(({ value, label, icon: Icon }) => <ToggleGroupItem key={value} value={value} className={segmentedItem}><Icon aria-hidden="true" />{label}</ToggleGroupItem>)}
      </ToggleGroup>
    </section>
  )
}

/** Model defaults and appearance. Keys and provider access stay on the server. */
export default function SettingsPage() {
  const models = useModels()
  const saved = useSavedSettings()
  const headingId = useId()
  const chatModels = models.data?.items.filter(isChatModel)
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <div className="mt-10 grid gap-10">
        <section aria-labelledby={headingId} className="grid gap-6">
          <div className="grid gap-1">
            <h2 id={headingId} className="text-base font-semibold tracking-tight">Default model</h2>
            <p className="text-sm text-pretty text-muted-foreground">Writes new summaries and answers questions. The composer can switch models for a single request.</p>
          </div>
          {(models.isPending || saved.isPending) && !(models.error || saved.error) && (
            <div role="status" className="grid gap-3"><span className="sr-only">Loading models…</span><Skeleton className="h-16 w-full rounded-xl" /><Skeleton className="h-16 w-full rounded-xl" /></div>
          )}
          <ErrorNotice error={models.error ?? saved.error} retry={() => { void models.refetch(); void saved.refetch() }} />
          {chatModels && saved.data && (chatModels.length ? (
            <ModelDefaults models={chatModels} saved={saved.data} labelledBy={headingId} />
          ) : (
            <EmptyState title="No models configured">Configure model access on the server, then reload this page.</EmptyState>
          ))}
        </section>
        <Separator />
        <RetrievalSettingsSection />
        <Separator />
        <MetadataSettingsSection /><Separator />
        {models.data?.items.some((model) => model.installation) && <><LocalModels models={models.data.items} defaultModel={saved.data?.default_model} /><Separator /></>}
        <Appearance />
        <Separator />
        <p className="text-sm text-pretty text-muted-foreground">API keys are managed on the server and never reach this browser. A model shows as unavailable until the server has access to it.</p>
      </div>
    </div>
  )
}
