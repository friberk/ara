import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const terra = { ...luna, key: 'gpt-5.6-terra', model_id: 'gpt-5.6-terra', display_name: 'GPT-5.6 Terra', status: 'configured', reasoning_efforts: ['none', 'low', 'medium', 'high'], supports_structured_output: false }
const unavailable = { ...luna, key: 'unavailable-exact', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [], supports_streaming: false, supports_structured_output: false }
afterEach(() => vi.unstubAllGlobals())

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
