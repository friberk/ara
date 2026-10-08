import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../api/client'
import type { Collection, GenerationSettings, Model, Settings } from '../api/types'
import { Button } from '../components/ui/button'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { ModelControls } from '../components/ModelControls'
function SettingsForm({ settings, models }: { settings: Settings; models: Model[] }) {
  const [value, setValue] = useState<GenerationSettings>({ model: settings.default_model, reasoning_effort: settings.reasoning_effort }); const client = useQueryClient(); const selected = models.find((model) => model.key === value.model)
  const mutation = useMutation({ mutationFn: () => api<Settings>('/settings', json('PUT', { default_model: value.model, reasoning_effort: value.reasoning_effort } satisfies Settings)), onSuccess: (data) => client.setQueryData(['settings'], data) })
  return <form className="settings-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><ModelControls models={models} value={value} onChange={(next) => { mutation.reset(); setValue(next) }}/><Button type="submit" disabled={mutation.isPending || !selected || selected.status === 'unavailable' || !selected.reasoning_efforts.includes(value.reasoning_effort)}>{mutation.isPending ? 'Saving…' : 'Save defaults'}</Button>{mutation.isSuccess && <p className="success" role="status">Model defaults saved.</p>}<ErrorNotice error={mutation.error}/></form>
}
export default function SettingsPage() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/settings') }); const models = useQuery({ queryKey: ['models'], queryFn: () => api<Collection<Model>>('/models') })
  return <section><h1>Model settings</h1><p className="lead">Choose the default model and reasoning effort for summaries and questions. You can change them for each request.</p>{(settings.isPending || models.isPending) && <Loading>Loading model settings…</Loading>}<ErrorNotice error={settings.error || models.error} retry={() => { void settings.refetch(); void models.refetch() }}/>{settings.data && models.data && <><SettingsForm key={`${settings.data.default_model}:${settings.data.reasoning_effort}`} settings={settings.data} models={models.data.items}/><h2 className="section-heading">Model access</h2>{!models.data.items.length ? <Empty title="No models configured">Configure model access on the server, then refresh this page.</Empty> : <ul className="model-list">{models.data.items.map((model) => <li key={model.key}><div><strong>{model.display_name}</strong><p className="small muted">{model.key} · {model.provider}</p></div><span className={`status status-${model.status}`}>{model.status}</span></li>)}</ul>}<p className="muted small">Unavailable models need server configuration or account access. API keys are managed on the server.</p></>}</section>
}
