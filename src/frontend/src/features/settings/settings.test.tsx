import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import type { Model } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { queryKeys } from '@/lib/query-keys'

const luna = { kind: 'chat' as const, key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const terra = { ...luna, key: 'gpt-5.6-terra', model_id: 'gpt-5.6-terra', display_name: 'GPT-5.6 Terra', status: 'configured', reasoning_efforts: ['none', 'low', 'medium', 'high'], supports_structured_output: false }
const unavailable = { ...luna, key: 'unavailable-exact', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [], supports_streaming: false, supports_structured_output: false }
afterEach(() => vi.unstubAllGlobals())

test('Given saved local Low reasoning and pending readiness, When verified capabilities return, Then Low is preserved without making defaults dirty', async () => {
  let local: Model = {
    ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B',
    status: 'unavailable', reasoning_efforts: ['default'], unavailable_code: 'LOCAL_MODEL_NOT_READY', unavailable_reason: 'Preparing model automatically.',
    installation: { state: 'queued', operation: 'verify', weights_present: true, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 5592218900, total_bytes: 5592218900, job_id: 'prepare-job', digest: null, updated_at: null, error: null },
  }
  const { calls } = mockApi({ 'GET /models': () => json({ items: [luna, local] }), 'GET /settings': { default_model: local.key, reasoning_effort: 'low' } })
  const { client } = renderApp('/settings')
  const choice = await screen.findByRole('radio', { name: 'K2 Horizon 7B' })
  const save = screen.getByRole('button', { name: 'Save defaults' })
  expect(choice).toBeChecked()
  expect(choice).toBeDisabled()
  expect(save).toBeDisabled()
  expect(screen.queryByRole('radiogroup', { name: 'Reasoning effort' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Reasoning' })).not.toBeInTheDocument()
  local = { ...local, status: 'available', unavailable_code: null, unavailable_reason: null, reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], installation: { ...local.installation!, state: 'ready', operation: null, job_id: null } }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await waitFor(() => expect(screen.getByRole('radio', { name: 'Low' })).toHaveAttribute('aria-checked', 'true'))
  expect(choice).toBeEnabled()
  expect(save).toBeDisabled()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given unavailable and supported models, Then exact IDs and reasoning capabilities govern selection', async () => {
  mockApi({ 'GET /models': { items: [luna, terra, unavailable] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = renderApp('/settings')
  const models = await screen.findByRole('radiogroup', { name: 'Default model' })
  await waitFor(() => expect(within(models).getByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked())
  expect(within(models).getByText('gpt-5.6-luna')).toBeVisible()
  const off = within(models).getByRole('radio', { name: 'Unavailable model' })
  expect(off).toBeDisabled()
  expect(off).toHaveAccessibleDescription(/Not configured on the server/)
  const effort = screen.getByRole('radiogroup', { name: 'Reasoning effort' })
  expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['Low', 'High'])
  expect(within(effort).getByRole('radio', { name: 'Low' })).toHaveAttribute('aria-checked', 'true')
  await user.click(within(models).getByRole('radio', { name: 'GPT-5.6 Terra' }))
  expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['None', 'Low', 'Medium', 'High'])
  expect(within(models).getByRole('radio', { name: 'GPT-5.6 Terra' })).toHaveAccessibleDescription(/Cannot write summaries/)
})

test('Given a changed default, When Save defaults is pressed, Then the exact model and effort are saved', async () => {
  const { calls } = mockApi({ 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'PUT /settings': { default_model: luna.key, reasoning_effort: 'high' } })
  const { user } = renderApp('/settings')
  const save = await screen.findByRole('button', { name: 'Save defaults' })
  await waitFor(() => expect(screen.getByRole('radio', { name: 'Low' })).toHaveAttribute('aria-checked', 'true'))
  expect(save).toBeDisabled()
  await user.click(screen.getByRole('radio', { name: 'High' }))
  await user.click(save)
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ default_model: luna.key, reasoning_effort: 'high' }))
  expect(await screen.findByText('Model defaults saved.')).toBeVisible()
  expect(screen.getByText(/API keys are managed on the server/)).toBeVisible()
})

test('Given the appearance setting, When Dark is chosen, Then the dark theme applies', async () => {
  mockApi({})
  const { user } = renderApp('/settings')
  const theme = await screen.findByRole('radiogroup', { name: 'Theme' })
  expect(within(theme).getByRole('radio', { name: 'System' })).toHaveAttribute('aria-checked', 'true')
  await user.click(within(theme).getByRole('radio', { name: 'Dark' }))
  await waitFor(() => expect(document.documentElement).toHaveClass('dark'))
  expect(window.localStorage.getItem('theme')).toBe('dark')
})


test('Given verified local named controls, When High is saved, Then Settings offers only explicit levels and sends high', async () => {
  const local = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' } }
  const { calls } = mockApi({ 'GET /models': { items: [luna, local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'low' }, 'PUT /settings': { default_model: local.key, reasoning_effort: 'high' } })
  const { user } = renderApp('/settings')
  const effort = await screen.findByRole('radiogroup', { name: 'Reasoning effort' })
  await waitFor(() => expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['None', 'Low', 'Medium', 'High']))
  await user.click(within(effort).getByRole('radio', { name: 'High' }))
  await user.click(screen.getByRole('button', { name: 'Save defaults' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ default_model: local.key, reasoning_effort: 'high' }))
  expect(await screen.findByText('Model defaults saved.')).toBeVisible()
})

test.each(['default', 'on'])('Given saved %s aliases High, Then Settings checks High without a dirty form or automatic save', async (reasoning) => {
  const local = { ...luna, key: 'native-named', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' } }
  const { calls } = mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: reasoning } })
  renderApp('/settings')
  const high = await screen.findByRole('radio', { name: 'High' })
  expect(high).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByRole('button', { name: 'Save defaults' })).toBeDisabled()
  expect(screen.queryByRole('radio', { name: 'Model default' })).not.toBeInTheDocument()
  expect(screen.queryByRole('radio', { name: 'On' })).not.toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given verified boolean-only reasoning, When toggled off, Then Settings saves none without invented effort levels', async () => {
  const local = { ...luna, key: 'native-boolean', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on'], reasoning_aliases: { default: 'on' } }
  const { calls } = mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' }, 'PUT /settings': { default_model: local.key, reasoning_effort: 'none' } })
  const { user } = renderApp('/settings')
  const toggle = await screen.findByRole('button', { name: 'Reasoning' })
  expect(toggle).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByRole('radiogroup', { name: 'Reasoning effort' })).not.toBeInTheDocument()
  await user.click(toggle)
  expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await user.click(screen.getByRole('button', { name: 'Save defaults' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ default_model: local.key, reasoning_effort: 'none' }))
})

test('Given unknown default semantics, Then Settings describes model-controlled reasoning rather than inventing a toggle', async () => {
  const local = { ...luna, key: 'native-unknown', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on'], reasoning_aliases: { default: 'unverified' } }
  mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' } })
  renderApp('/settings')
  expect(await screen.findByText('Reasoning is controlled by this model.')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Reasoning' })).not.toBeInTheDocument()
  expect(screen.queryByRole('radiogroup', { name: 'Reasoning effort' })).not.toBeInTheDocument()
})

test('Given hosted Max switches to native High, When the native preset changes, Then the unsaved explicit High choice is preserved', async () => {
  const hosted = { ...luna, reasoning_efforts: ['low', 'max'] }
  let local = { ...luna, key: 'native', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'high'], reasoning_aliases: { default: 'high', on: 'high' }, display_name: 'Native model' }
  mockApi({ 'GET /models': () => json({ items: [hosted, local] }), 'GET /settings': { default_model: hosted.key, reasoning_effort: 'max' } })
  const { client, user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'Native model' }))
  expect(screen.getByRole('radio', { name: 'High' })).toHaveAttribute('aria-checked', 'true')
  local = { ...local, reasoning_aliases: { default: 'low', on: 'low' }, display_name: 'Updated native model' }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await screen.findByRole('radio', { name: 'Updated native model' })
  expect(screen.getByRole('radio', { name: 'High' })).toHaveAttribute('aria-checked', 'true')
})

test('Given local chat, search and ranking models, Then Default model lists chat models only and Local models labels the other kinds', async () => {
  const weights = { state: 'ready', operation: null, weights_present: true, quantization: 'Q4_K_M', download_bytes: 2500000000, completed_bytes: 2500000000, total_bytes: 2500000000, job_id: null, digest: null, updated_at: null, error: null }
  const chat = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', reasoning_efforts: ['default'], installation: weights }
  const search = { ...chat, kind: 'embedding', key: 'qwen3-embedding-4b', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B' }
  const ranking = { ...chat, kind: 'reranker', key: 'qwen3-reranker', model_id: 'qwen3-reranker:0.6b', display_name: 'Qwen3 Reranker' }
  mockApi({ 'GET /models': { items: [luna, search, chat, ranking] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  renderApp('/settings')
  const models = await screen.findByRole('radiogroup', { name: 'Default model' })
  await waitFor(() => expect(within(models).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual([luna.key, chat.key]))
  const local = screen.getByRole('region', { name: 'Local models' })
  expect(within(within(local).getByRole('region', { name: 'Manage Qwen3 Embedding 4B' })).getByText('Search')).toBeVisible()
  expect(within(within(local).getByRole('region', { name: 'Manage Qwen3 Reranker' })).getByText('Ranking')).toBeVisible()
  const chatRow = within(local).getByRole('region', { name: 'Manage K2 Horizon 7B' })
  expect(within(chatRow).queryByText('Search')).not.toBeInTheDocument()
  expect(within(chatRow).queryByText('Ranking')).not.toBeInTheDocument()
})
