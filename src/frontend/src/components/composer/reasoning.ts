import type { GenerationSettings, Message, Model } from '@/api/types'

type ReasoningControls = { kind: 'levels' | 'boolean' | 'controlled'; options: string[] }

/** Resolve only aliases declared by this ready model and backed by its supported controls. */
function canonicalEffort(model: Model, effort: string) {
  if (model.provider !== 'ollama' || model.status === 'unavailable') return effort
  const target = model.reasoning_aliases?.[effort]
  return target && model.reasoning_efforts.includes(target) ? target : effort
}

/** Menus expose explicit levels; boolean controls require a proven default interpretation. */
export function reasoningControls(model: Model | undefined): ReasoningControls {
  if (!model || model.status === 'unavailable') return { kind: 'controlled', options: [] }
  if (model.provider !== 'ollama') return { kind: 'levels', options: model.reasoning_efforts }
  const named = model.reasoning_efforts.filter((effort) => !['default', 'none', 'on'].includes(effort))
  if (named.length) return { kind: 'levels', options: model.reasoning_efforts.filter((effort) => effort !== 'default' && effort !== 'on') }
  const preset = canonicalEffort(model, 'default')
  if (model.reasoning_efforts.includes('none') && model.reasoning_efforts.includes('on') && (preset === 'none' || preset === 'on')) {
    return { kind: 'boolean', options: ['none', 'on'] }
  }
  return { kind: 'controlled', options: [] }
}

/** Derive future requests without rewriting the underlying saved or session preference. */
export function normaliseSettings(models: Model[], value: GenerationSettings): GenerationSettings {
  const model = models.find((item) => item.key === value.model)
  if (!model || model.status === 'unavailable') return value
  const effort = canonicalEffort(model, value.reasoning_effort)
  if (model.reasoning_efforts.includes(effort)) return { ...value, reasoning_effort: effort }
  const controls = reasoningControls(model)
  const preset = canonicalEffort(model, 'default')
  const fallback = controls.options.includes(preset) ? preset : controls.options[0] ?? model.reasoning_efforts[0] ?? 'none'
  return { ...value, reasoning_effort: fallback }
}

/** The selection a chat's latest answer used, if that model is still available; otherwise null. */
export function restoreChatSettings(models: Model[], messages: Pick<Message, 'role' | 'model' | 'reasoning_effort'>[]): GenerationSettings | null {
  const last = [...messages].reverse().find((message) => message.role === 'assistant' && message.model)
  const model = models.find((item) => item.key === last?.model)
  if (!last?.model || !model || model.status === 'unavailable') return null
  return normaliseSettings(models, { model: last.model, reasoning_effort: last.reasoning_effort ?? 'none' })
}
