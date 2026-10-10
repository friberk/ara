// Search and retrieval settings (ARA-075): the default search model, separate from the chat model defaults.
import { screen, waitFor, within } from '@testing-library/react'
import type { EmbeddingProfile, Reranker, RetrievalSettings } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

const luna = { kind: 'chat' as const, key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const openai: EmbeddingProfile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null }
const qwen4b: EmbeddingProfile = { key: 'qwen3-embed-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', dimensions: 2560, status: 'unavailable', unavailable_reason: 'Download Qwen3 Embedding 4B in Settings', local_model_key: 'qwen3-embedding-4b' }
const qwen8b: EmbeddingProfile = { ...qwen4b, key: 'qwen3-embed-8b', model_id: 'qwen3-embedding:8b', display_name: 'Qwen3 Embedding 8B', dimensions: 4096, unavailable_reason: 'Download Qwen3 Embedding 8B in Settings', local_model_key: 'qwen3-embedding-8b' }
const profiles = { items: [openai, qwen4b, qwen8b], default_profile: openai.key }
const saved: RetrievalSettings = { embedding_profile: openai.key, reranker: 'openai-gpt-6-luna' }
const base = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'GET /retrieval/profiles': profiles }
afterEach(() => vi.unstubAllGlobals())
// Local model tests run with open models on, as the server reports them (ARA-090).
const openModels = { 'GET /features': { open_models: true } }

test('Given three search models with OpenAI saved, Then Settings lists them with OpenAI chosen and exact ids in mono', async () => {
  mockApi({ ...openModels, ...base, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Search and retrieval' })
  const choices = await within(section).findByRole('radiogroup', { name: 'Default search model' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['openai-3-large', 'qwen3-embed-4b', 'qwen3-embed-8b'])
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toBeChecked()
  expect(within(choices).getByText('text-embedding-3-large')).toHaveClass('font-mono')
  expect(within(section).getByRole('button', { name: 'Save search settings' })).toBeDisabled()
})

test('Given Qwen 4B is not downloaded, Then its reason links to Local models and it can still be chosen', async () => {
  mockApi({ ...openModels, ...base, 'GET /retrieval/settings': saved })
  const { user } = renderApp('/settings')
  const qwen = await screen.findByRole('radio', { name: 'Qwen3 Embedding 4B' })
  expect(qwen).toHaveAccessibleDescription(/Download Qwen3 Embedding 4B in Settings/)
  const option = qwen.closest('label') as HTMLElement
  expect(within(option).getByRole('link', { name: 'Go to Local models' })).toHaveAttribute('href', '/settings#local-models')
  expect(qwen).toBeEnabled()
  await user.click(qwen)
  expect(qwen).toBeChecked()
  expect(screen.getByRole('button', { name: 'Save search settings' })).toBeEnabled()
})

test('Given a new choice, When Save search settings is pressed, Then PUT sends the chosen key and keeps the saved reranker choice', async () => {
  // Saving the search model must not overwrite the stored reranker choice.
  const stored: RetrievalSettings = { ...saved, reranker: 'qwen3-rerank-0.6b' }
  const { calls } = mockApi({ ...openModels, ...base, 'GET /retrieval/settings': stored, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'Qwen3 Embedding 8B' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/retrieval/settings')?.body).toEqual({ embedding_profile: 'qwen3-embed-8b', reranker: 'qwen3-rerank-0.6b' }))
  expect(await screen.findByText('Search settings saved.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Save search settings' })).toBeDisabled()
})

// Reranker profiles come from the server's catalog (ARA-074); the UI renders whatever it lists, plus Off.
const hostedRerank: Reranker = { key: 'openai-gpt-6-luna', provider: 'openai', model_id: 'gpt-6-luna', display_name: 'GPT-6 Luna', status: 'available', unavailable_reason: null, local_model_key: null, candidates: 30 }
const localRerank: Reranker = { key: 'qwen3-rerank-0.6b', provider: 'ollama', model_id: 'dengcao/Qwen3-Reranker-0.6B:F16', display_name: 'Qwen3 Reranker 0.6B', status: 'unavailable', unavailable_reason: 'Download Qwen3 Reranker 0.6B in Settings.', local_model_key: 'qwen3-reranker-0.6b', candidates: 15 }
const withRerankers = { ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank, localRerank] } }

test('Given catalog rerankers, Then Rerank results lists each with its id and what it costs, plus Off, with the saved one chosen', async () => {
  mockApi({ ...openModels, ...withRerankers, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const choices = await screen.findByRole('radiogroup', { name: 'Rerank results' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['openai-gpt-6-luna', 'qwen3-rerank-0.6b', ''])
  const hosted = within(choices).getByRole('radio', { name: 'GPT-6 Luna' })
  expect(hosted).toBeChecked()
  expect(hosted).toBeEnabled()
  expect(hosted).toHaveAccessibleDescription('gpt-6-luna Fast, with a small cost per answer.')
  expect(within(choices).getByText('gpt-6-luna')).toHaveClass('font-mono')
  expect(within(choices).getByRole('radio', { name: 'Off' })).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Save search settings' })).toBeDisabled()
})

test('Given a local reranker that is not installed, Then it cannot be chosen and its reason links to Local models', async () => {
  mockApi({ ...openModels, ...withRerankers, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const local = await screen.findByRole('radio', { name: 'Qwen3 Reranker 0.6B' })
  expect(local).toBeDisabled()
  expect(local).toHaveAccessibleDescription(/^dengcao\/Qwen3-Reranker-0\.6B:F16 Private\. Adds about 10 seconds to each answer\. Download Qwen3 Reranker 0\.6B in Settings\./)
  expect(within(local.closest('label') as HTMLElement).getByRole('link', { name: 'Go to Local models' })).toHaveAttribute('href', '/settings#local-models')
})

test('Given an installed local reranker, When it is chosen and saved, Then PUT sends its key with the saved search model', async () => {
  const { calls } = mockApi({ ...openModels, ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank, { ...localRerank, status: 'available', unavailable_reason: null }] }, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'Qwen3 Reranker 0.6B' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/retrieval/settings')?.body).toEqual({ embedding_profile: 'openai-3-large', reranker: 'qwen3-rerank-0.6b' }))
  expect(await screen.findByText('Search settings saved.')).toBeVisible()
  expect(screen.getByRole('radio', { name: 'Qwen3 Reranker 0.6B' })).toBeChecked()
})

test('Given reranking is on, When Off is chosen and saved, Then PUT sends reranker null', async () => {
  const { calls } = mockApi({ ...withRerankers, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'Off' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/retrieval/settings')?.body).toEqual({ embedding_profile: 'openai-3-large', reranker: null }))
})

test('Given reranking saved off, Then Off is chosen', async () => {
  mockApi({ ...withRerankers, 'GET /retrieval/settings': { ...saved, reranker: null } })
  renderApp('/settings')
  expect(await screen.findByRole('radio', { name: 'Off' })).toBeChecked()
  expect(screen.getByRole('radio', { name: 'GPT-6 Luna' })).not.toBeChecked()
})

test('Given a server that lists no rerankers, Then only Off is offered', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': { ...saved, reranker: null } })
  renderApp('/settings')
  const choices = await screen.findByRole('radiogroup', { name: 'Rerank results' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual([''])
})

test('Given retrieval settings fail to load, Then the section explains it inline and the chat defaults still work', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': () => json({ code: 'NOT_IMPLEMENTED', message: 'Search settings are not available yet.' }, 501) })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Search and retrieval' })
  expect(await within(section).findByRole('alert')).toHaveTextContent('Search settings are not available yet.')
  expect(within(section).getByRole('button', { name: 'Try again' })).toBeEnabled()
  expect(await within(await screen.findByRole('radiogroup', { name: 'Default model' })).findByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked()
})
