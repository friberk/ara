import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { testClient } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'
import { queryKeys } from '@/lib/query-keys'
import { GenerationSettingsProvider } from './generation-settings'
import { useGenerationSettings } from './generation-settings-context'

const model = (key: string, overrides: Record<string, unknown> = {}) => ({ key, provider: 'openai', model_id: key, display_name: key, status: 'configured', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000, ...overrides })
afterEach(() => vi.unstubAllGlobals())

function mount() {
  const client = testClient()
  return { client, ...renderHook(() => useGenerationSettings(), { wrapper: ({ children }) => <QueryClientProvider client={client}><GenerationSettingsProvider>{children}</GenerationSettingsProvider></QueryClientProvider> }) }
}

test('Given saved defaults, Then they are the selection', async () => {
  mockApi({ 'GET /models': { items: [model('luna')] }, 'GET /settings': { default_model: 'luna', reasoning_effort: 'high' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'luna', reasoning_effort: 'high' }))
  expect(result.current.usableFor('chat')).toBe(true)
})

test('Given a saved effort the model no longer supports, Then the selection falls back to the model’s first effort', async () => {
  mockApi({ 'GET /models': { items: [model('luna', { reasoning_efforts: ['medium'] })] }, 'GET /settings': { default_model: 'luna', reasoning_effort: 'high' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'luna', reasoning_effort: 'medium' }))
})

test('Given no saved default, Then the first configured model is chosen, skipping unavailable ones', async () => {
  mockApi({ 'GET /models': { items: [model('off', { status: 'unavailable' }), model('terra')] }, 'GET /settings': { default_model: '', reasoning_effort: 'low' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'terra', reasoning_effort: 'low' }))
})

test('Given default settings cannot be loaded, Then an available paid model is never selected automatically', async () => {
  mockApi({ 'GET /models': { items: [model('gpt-5.6-luna')] }, 'GET /settings': () => json({ code: 'SETTINGS_UNAVAILABLE', message: 'Try again.' }, 503) })
  const { result } = mount()
  await waitFor(() => expect(result.current.error).toBeTruthy())
  expect(result.current.settings.model).toBe('')
  expect(result.current.usableFor('chat')).toBe(false)
  expect(result.current.usableFor('summary')).toBe(false)
})

test('Given the saved local default is unavailable, Then its model identity survives beside an available paid model', async () => {
  const localKey = 'ifm-k2-horizon-7b'
  mockApi({ 'GET /models': { items: [model('gpt-5.6-luna'), model(localKey, { provider: 'ollama', status: 'unavailable', reasoning_efforts: ['default', 'none'] })] }, 'GET /settings': { default_model: localKey, reasoning_effort: 'none' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings.model).toBe(localKey))
  expect(result.current.settings.reasoning_effort).toBe('none')
  expect(result.current.usableFor('chat')).toBe(false)
})

test('Given a session choice, Then it overrides the default and usability follows the model capabilities', async () => {
  mockApi({ 'GET /models': { items: [model('luna'), model('batch', { supports_streaming: false })] }, 'GET /settings': { default_model: 'luna', reasoning_effort: 'low' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings.model).toBe('luna'))
  act(() => result.current.setSettings({ model: 'batch', reasoning_effort: 'high' }))
  expect(result.current.settings).toEqual({ model: 'batch', reasoning_effort: 'high' })
  expect(result.current.usableFor('chat')).toBe(false)
  expect(result.current.usableFor('summary')).toBe(true)
})

test.each(['default', 'on'])('Given declared supported %s alias, Then prospective selection and default comparison use High', async (reasoning) => {
  const local = model('native', { provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' } })
  mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: reasoning } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'native', reasoning_effort: 'high' }))
  expect(result.current.savedDefaults).toEqual({ model: 'native', reasoning_effort: 'high' })
  expect(result.current.usableFor('chat')).toBe(true)
})

test.each(['unverified', 'max'])('Given an unsupported alias target %s, Then it is ignored without inventing High', async (target) => {
  const local = model('native', { provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'high'], reasoning_aliases: { default: target, on: target } })
  mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'native', reasoning_effort: 'default' }))
})

test('Given pending local capabilities, Then its raw Low preference stays preserved and generation is blocked', async () => {
  const local = model('native', { provider: 'ollama', status: 'unavailable', reasoning_efforts: ['default'], reasoning_aliases: {} })
  mockApi({ 'GET /models': { items: [model('hosted'), local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'low' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'native', reasoning_effort: 'low' }))
  expect(result.current.usableFor('chat')).toBe(false)
})

test('Given switching from hosted Max chooses native High, When its runtime preset later changes, Then the explicit session choice remains High', async () => {
  let local = { ...model('native', { provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'high'] }), reasoning_aliases: { default: 'high', on: 'high' } }
  const hosted = model('hosted', { reasoning_efforts: ['low', 'max'] })
  mockApi({ 'GET /models': () => json({ items: [hosted, local] }), 'GET /settings': { default_model: hosted.key, reasoning_effort: 'max' } })
  const { client, result } = mount()
  await waitFor(() => expect(result.current.settings.model).toBe(hosted.key))
  act(() => result.current.setSettings({ model: local.key, reasoning_effort: 'max' }))
  expect(result.current.settings).toEqual({ model: 'native', reasoning_effort: 'high' })
  local = { ...local, reasoning_aliases: { default: 'low', on: 'low' } }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await waitFor(() => expect(result.current.selectedModel?.reasoning_aliases?.default).toBe('low'))
  expect(result.current.settings).toEqual({ model: 'native', reasoning_effort: 'high' })
})

test('Given no saved default and a search model listed first, Then the first chat model is chosen', async () => {
  mockApi({ 'GET /models': { items: [model('qwen3-embedding-4b', { kind: 'embedding', provider: 'ollama' }), model('terra', { kind: 'chat' })] }, 'GET /settings': { default_model: '', reasoning_effort: 'low' } })
  const { result } = mount()
  await waitFor(() => expect(result.current.settings).toEqual({ model: 'terra', reasoning_effort: 'low' }))
  expect(result.current.models.map((item) => item.key)).toEqual(['terra'])
})
