import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import type { Model } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { queryKeys } from '@/lib/query-keys'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
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


test('Given local boolean and named thinking controls, When saved in Settings, Then the exact selection persists', async () => {
  const local = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'] }
  const { calls } = mockApi({ 'GET /models': { items: [luna, local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' }, 'PUT /settings': { default_model: local.key, reasoning_effort: 'on' } })
  const { user } = renderApp('/settings')
  const effort = await screen.findByRole('radiogroup', { name: 'Reasoning effort' })
  await waitFor(() => expect(within(effort).getAllByRole('radio').map((item) => item.textContent)).toEqual(['Model default', 'None', 'On', 'Low', 'Medium', 'High']))
  await user.click(within(effort).getByRole('radio', { name: 'On' }))
  await user.click(screen.getByRole('button', { name: 'Save defaults' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ default_model: local.key, reasoning_effort: 'on' }))
  expect(await screen.findByText('Model defaults saved.')).toBeVisible()
})
