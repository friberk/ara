// The Models and General categories of the Settings dialog (ARA-109). Choices save as they are made.
import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import type { Model } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { queryKeys } from '@/lib/query-keys'

const luna: Model = { kind: 'chat', key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 1_050_000, description: 'Built for cost-sensitive, high-volume work.', input_price_per_million: 0.2, output_price_per_million: 1.2 }
const terra: Model = { ...luna, key: 'gpt-5.6-terra', model_id: 'gpt-5.6-terra', display_name: 'GPT-5.6 Terra', status: 'configured', reasoning_efforts: ['none', 'low', 'medium', 'high'], supports_structured_output: false, description: 'Balances intelligence and cost.', input_price_per_million: 2, output_price_per_million: 12 }
const sol: Model = { ...luna, key: 'gpt-5.6-sol', model_id: 'gpt-5.6-sol', display_name: 'GPT-5.6 Sol', status: 'configured', description: 'Flagship model for complex professional work.', input_price_per_million: 4, output_price_per_million: 20 }
const unavailable: Model = { ...luna, key: 'unavailable-exact', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [], supports_streaming: false, supports_structured_output: false }
const lunaLow = { default_model: luna.key, reasoning_effort: 'low' }
afterEach(() => vi.unstubAllGlobals())
// Local model tests run with open models on, as the server reports them (ARA-090).
const openModels = { 'GET /features': { open_models: true } }
const lastPut = (calls: { method: string; path: string; body: unknown }[]) => calls.filter((call) => call.method === 'PUT' && call.path === '/settings').at(-1)?.body

test('Given the hosted catalog, Then each model says what it is for, what it costs and how much it reads, and the default is marked', async () => {
  mockApi({ 'GET /models': { items: [sol, terra, luna] }, 'GET /settings': lunaLow })
  renderApp('/?settings=models')
  const section = await screen.findByRole('region', { name: 'Default model' })
  const models = await within(section).findByRole('radiogroup', { name: 'Default model' })
  await waitFor(() => expect(within(models).getByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked())
  expect(within(models).getByRole('radio', { name: 'GPT-5.6 Sol' })).toHaveAccessibleDescription('Flagship model for complex professional work. Input $4.00 Output $20.00 Context 1.05M')
  expect(within(models).getByRole('radio', { name: 'GPT-5.6 Luna' })).toHaveAccessibleDescription(/^Built for cost-sensitive, high-volume work\. Input \$0\.20 Output \$1\.20 Context 1\.05M/)
  const luneRow = within(models).getByRole('radio', { name: 'GPT-5.6 Luna' }).closest('label') as HTMLElement
  expect(within(luneRow).getByText('Default')).toBeVisible()
  expect(within(models).getAllByText('Default')).toHaveLength(1)
  expect(within(section).getByText('Prices are in US dollars per million tokens. Context is how much text a model can read at once.')).toBeVisible()
  expect(within(section).getByText(/Any chat can switch to another model from the menu next to the send button\./)).toBeVisible()
  expect(within(models).queryByText('gpt-5.6-luna')).not.toBeInTheDocument()
  expect(within(models).queryByText(/Configured|Available/)).not.toBeInTheDocument()
})

test('Given saved local Low reasoning and pending readiness, When verified capabilities return, Then Low is preserved without saving anything', async () => {
  let local: Model = {
    ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', description: null, input_price_per_million: null, output_price_per_million: null,
    status: 'unavailable', reasoning_efforts: ['default'], unavailable_code: 'LOCAL_MODEL_NOT_READY', unavailable_reason: 'Preparing model automatically.',
    installation: { state: 'queued', operation: 'verify', weights_present: true, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 5592218900, total_bytes: 5592218900, job_id: 'prepare-job', digest: null, updated_at: null, error: null },
  }
  const { calls } = mockApi({ 'GET /models': () => json({ items: [luna, local] }), 'GET /settings': { default_model: local.key, reasoning_effort: 'low' } })
  const { client } = renderApp('/?settings=models')
  const choice = await screen.findByRole('radio', { name: 'K2 Horizon 7B' })
  expect(choice).toBeChecked()
  expect(choice).toBeDisabled()
  expect(choice).toHaveAccessibleDescription(/Preparing model automatically\./)
  expect(screen.queryByRole('radiogroup', { name: 'Reasoning' })).not.toBeInTheDocument()
  expect(screen.queryByRole('switch', { name: 'Reasoning' })).not.toBeInTheDocument()
  local = { ...local, status: 'available', unavailable_code: null, unavailable_reason: null, reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], installation: { ...local.installation!, state: 'ready', operation: null, job_id: null } }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await waitFor(() => expect(screen.getByRole('radio', { name: 'Low' })).toHaveAttribute('aria-checked', 'true'))
  expect(choice).toBeEnabled()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given unavailable and limited models, Then the reason and the limit are said plainly and reasoning follows the chosen model', async () => {
  mockApi({ 'GET /models': { items: [luna, terra, unavailable] }, 'GET /settings': lunaLow, 'PUT /settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=models')
  const models = await screen.findByRole('radiogroup', { name: 'Default model' })
  await waitFor(() => expect(within(models).getByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked())
  const off = within(models).getByRole('radio', { name: 'Unavailable model' })
  expect(off).toBeDisabled()
  expect(off).toHaveAccessibleDescription(/Add an OpenAI API key to the server, then restart it\./)
  expect(within(models).getByRole('radio', { name: 'GPT-5.6 Terra' })).toHaveAccessibleDescription(/Can’t write paper summaries\./)
  const effort = screen.getByRole('radiogroup', { name: 'Reasoning' })
  expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['Low', 'High'])
  expect(within(effort).getByRole('radio', { name: 'Low' })).toHaveAttribute('aria-checked', 'true')
  await user.click(within(models).getByRole('radio', { name: 'GPT-5.6 Terra' }))
  await waitFor(() => expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['None', 'Low', 'Medium', 'High']))
})

test('Given a reasoning level, When it is chosen, Then the exact model and level save at once and the section says so', async () => {
  const { calls } = mockApi({ 'GET /models': { items: [luna] }, 'GET /settings': lunaLow, 'PUT /settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=models')
  const section = await screen.findByRole('region', { name: 'Reasoning' })
  await waitFor(() => expect(within(section).getByRole('radio', { name: 'Low' })).toHaveAttribute('aria-checked', 'true'))
  expect(within(section).getByText(/More reasoning helps with hard questions/)).toBeVisible()
  await user.click(within(section).getByRole('radio', { name: 'High' }))
  await waitFor(() => expect(lastPut(calls)).toEqual({ default_model: luna.key, reasoning_effort: 'high' }))
  expect(await within(section).findByText('Saved')).toBeVisible()
  expect(within(section).getByRole('radio', { name: 'High' })).toHaveAttribute('aria-checked', 'true')
})

test('Given a changed default model, When it is chosen, Then PUT sends only the model and effort, and the Default mark moves', async () => {
  const { calls } = mockApi({ 'GET /models': { items: [luna, terra] }, 'GET /settings': { ...lunaLow, memory_model: luna.key }, 'PUT /settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=models')
  const section = await screen.findByRole('region', { name: 'Default model' })
  await user.click(await within(section).findByRole('radio', { name: 'GPT-5.6 Terra' }))
  await waitFor(() => expect(lastPut(calls)).toEqual({ default_model: terra.key, reasoning_effort: 'low' }))
  expect(await within(section).findByText('Saved')).toBeVisible()
  const terraRow = within(section).getByRole('radio', { name: 'GPT-5.6 Terra' }).closest('label') as HTMLElement
  await waitFor(() => expect(within(terraRow).getByText('Default')).toBeVisible())
  expect(within(section).getAllByText('Default')).toHaveLength(1)
})

test('Given the save fails, Then the saved model stays chosen and the error is shown in place', async () => {
  mockApi({ 'GET /models': { items: [luna, terra] }, 'GET /settings': lunaLow, 'PUT /settings': () => json({ code: 'INTERNAL_ERROR', message: 'The default could not be saved.' }, 500) })
  const { user } = renderApp('/?settings=models')
  const section = await screen.findByRole('region', { name: 'Default model' })
  await user.click(await within(section).findByRole('radio', { name: 'GPT-5.6 Terra' }))
  expect(await within(section).findByRole('alert')).toHaveTextContent('The default could not be saved.')
  expect(within(section).getByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked()
})

test('Given the theme setting, When Dark is chosen, Then the dark theme applies', async () => {
  mockApi({})
  const { user } = renderApp('/?settings=general')
  const section = await screen.findByRole('region', { name: 'Theme' })
  const theme = within(section).getByRole('radiogroup', { name: 'Theme' })
  expect(within(theme).getAllByRole('radio').map((item) => item.textContent)).toEqual(['System', 'Light', 'Dark'])
  expect(within(theme).getByRole('radio', { name: 'System' })).toHaveAttribute('aria-checked', 'true')
  expect(within(section).getByText('System follows your device’s light or dark setting.')).toBeVisible()
  await user.click(within(theme).getByRole('radio', { name: 'Dark' }))
  await waitFor(() => expect(document.documentElement).toHaveClass('dark'))
  expect(window.localStorage.getItem('theme')).toBe('dark')
})

test('Given verified local named controls, When High is chosen, Then Settings offers only explicit levels and saves high', async () => {
  const local = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' } }
  const { calls } = mockApi({ 'GET /models': { items: [luna, local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'low' }, 'PUT /settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=models')
  const effort = await screen.findByRole('radiogroup', { name: 'Reasoning' })
  await waitFor(() => expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['None', 'Low', 'Medium', 'High']))
  await user.click(within(effort).getByRole('radio', { name: 'High' }))
  await waitFor(() => expect(lastPut(calls)).toEqual({ default_model: local.key, reasoning_effort: 'high' }))
})

test.each(['default', 'on'])('Given saved %s aliases High, Then Settings checks High without saving anything', async (reasoning) => {
  const local = { ...luna, key: 'native-named', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' } }
  const { calls } = mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: reasoning } })
  renderApp('/?settings=models')
  const high = await screen.findByRole('radio', { name: 'High' })
  expect(high).toHaveAttribute('aria-checked', 'true')
  expect(screen.queryByRole('radio', { name: 'Runtime preset' })).not.toBeInTheDocument()
  expect(screen.queryByRole('radio', { name: 'On' })).not.toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given verified boolean-only reasoning, When switched off, Then Settings saves none without invented levels', async () => {
  const local = { ...luna, key: 'native-boolean', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on'], reasoning_aliases: { default: 'on' } }
  const { calls } = mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' }, 'PUT /settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=models')
  const toggle = await screen.findByRole('switch', { name: 'Reasoning' })
  expect(toggle).toBeChecked()
  expect(screen.queryByRole('radiogroup', { name: 'Reasoning' })).not.toBeInTheDocument()
  await user.click(toggle)
  await waitFor(() => expect(lastPut(calls)).toEqual({ default_model: local.key, reasoning_effort: 'none' }))
})

test('Given unknown default semantics, Then Settings says the model decides rather than inventing a control', async () => {
  const local = { ...luna, key: 'native-unknown', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on'], reasoning_aliases: { default: 'unverified' } }
  mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' } })
  renderApp('/?settings=models')
  expect(await screen.findByText('This model decides how much to reason.')).toBeVisible()
  expect(screen.queryByRole('switch', { name: 'Reasoning' })).not.toBeInTheDocument()
  expect(screen.queryByRole('radiogroup', { name: 'Reasoning' })).not.toBeInTheDocument()
})

test('Given hosted Max switches to native, When the native preset later changes, Then the explicit High that was saved stays chosen', async () => {
  const hosted = { ...luna, reasoning_efforts: ['low', 'max'] }
  let local = { ...luna, key: 'native', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'high'], reasoning_aliases: { default: 'high', on: 'high' }, display_name: 'Native model' }
  let saved = { default_model: hosted.key, reasoning_effort: 'max' }
  const { calls } = mockApi({ ...openModels, 'GET /models': () => json({ items: [hosted, local] }), 'GET /settings': () => json(saved), 'PUT /settings': ({ body }) => json(saved = body as typeof saved) })
  const { client, user } = renderApp('/?settings=models')
  await user.click(await screen.findByRole('radio', { name: 'Native model' }))
  await waitFor(() => expect(lastPut(calls)).toEqual({ default_model: local.key, reasoning_effort: 'high' }))
  expect(screen.getByRole('radio', { name: 'High' })).toHaveAttribute('aria-checked', 'true')
  local = { ...local, reasoning_aliases: { default: 'low', on: 'low' }, display_name: 'Updated native model' }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await screen.findByRole('radio', { name: 'Updated native model' })
  expect(screen.getByRole('radio', { name: 'High' })).toHaveAttribute('aria-checked', 'true')
})

test('Given local chat, search and ranking models, Then Default model lists chat models only and Open models labels the other kinds', async () => {
  const weights = { state: 'ready', operation: null, weights_present: true, quantization: 'Q4_K_M', download_bytes: 2500000000, completed_bytes: 2500000000, total_bytes: 2500000000, job_id: null, digest: null, updated_at: null, error: null }
  const chat = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', reasoning_efforts: ['default'], installation: weights, description: null, input_price_per_million: null, output_price_per_million: null, context_window: 8192 }
  const search = { ...chat, kind: 'embedding', key: 'qwen3-embedding-4b', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B' }
  const ranking = { ...chat, kind: 'reranker', key: 'qwen3-reranker', model_id: 'qwen3-reranker:0.6b', display_name: 'Qwen3 Reranker' }
  mockApi({ ...openModels, 'GET /models': { items: [luna, search, chat, ranking] }, 'GET /settings': lunaLow })
  const { user } = renderApp('/?settings=models')
  const models = await screen.findByRole('radiogroup', { name: 'Default model' })
  await waitFor(() => expect(within(models).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual([luna.key, chat.key]))
  expect(within(models).getByRole('radio', { name: 'K2 Horizon 7B' })).toHaveAccessibleDescription('Runs on this server, with no per-token cost. Context 8.2k')
  await user.click(screen.getByRole('tab', { name: 'Open models' }))
  const local = await screen.findByRole('region', { name: 'Local models' })
  expect(within(within(local).getByRole('region', { name: 'Manage Qwen3 Embedding 4B' })).getByText('Search')).toBeVisible()
  expect(within(within(local).getByRole('region', { name: 'Manage Qwen3 Reranker' })).getByText('Ranking')).toBeVisible()
  const chatRow = within(local).getByRole('region', { name: 'Manage K2 Horizon 7B' })
  expect(within(chatRow).queryByText('Search')).not.toBeInTheDocument()
  expect(within(chatRow).queryByText('Ranking')).not.toBeInTheDocument()
})

test('Given hosted and local chat models, Then there is no separate summaries or follow-up model control', async () => {
  const local = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', reasoning_efforts: ['default'] }
  mockApi({ 'GET /models': { items: [luna, terra, local] }, 'GET /settings': lunaLow })
  renderApp('/?settings=models')
  await screen.findByRole('radiogroup', { name: 'Default model' })
  expect(screen.queryByRole('radiogroup', { name: /summaries and follow-up/i })).toBeNull()
  expect(screen.queryByText(/summaries and follow-up/i)).toBeNull()
})
