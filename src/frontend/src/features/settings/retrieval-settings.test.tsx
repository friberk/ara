// Search and retrieval settings (ARA-075): the default search model, separate from the chat model defaults.
import { screen, waitFor, within } from '@testing-library/react'
import type { EmbeddingProfile, RetrievalSettings } from '@/api/types'
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

test('Given three search models with OpenAI saved, Then Settings lists them with OpenAI chosen and exact ids in mono', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Search and retrieval' })
  const choices = await within(section).findByRole('radiogroup', { name: 'Default search model' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['openai-3-large', 'qwen3-embed-4b', 'qwen3-embed-8b'])
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toBeChecked()
  expect(within(choices).getByText('text-embedding-3-large')).toHaveClass('font-mono')
  expect(within(section).getByRole('button', { name: 'Save search model' })).toBeDisabled()
})

test('Given Qwen 4B is not downloaded, Then its reason links to Local models and it can still be chosen', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': saved })
  const { user } = renderApp('/settings')
  const qwen = await screen.findByRole('radio', { name: 'Qwen3 Embedding 4B' })
  expect(qwen).toHaveAccessibleDescription(/Download Qwen3 Embedding 4B in Settings/)
  const option = qwen.closest('label') as HTMLElement
  expect(within(option).getByRole('link', { name: 'Go to Local models' })).toHaveAttribute('href', '/settings#local-models')
  expect(qwen).toBeEnabled()
  await user.click(qwen)
  expect(qwen).toBeChecked()
  expect(screen.getByRole('button', { name: 'Save search model' })).toBeEnabled()
})

test('Given a new choice, When Save search model is pressed, Then PUT sends the chosen key and keeps the saved reranker choice', async () => {
  // Saving the search model must not overwrite the stored reranker choice.
  const stored: RetrievalSettings = { ...saved, reranker: 'qwen3-rerank-0.6b' }
  const { calls } = mockApi({ ...base, 'GET /retrieval/settings': stored, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'Qwen3 Embedding 8B' }))
  await user.click(screen.getByRole('button', { name: 'Save search model' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/retrieval/settings')?.body).toEqual({ embedding_profile: 'qwen3-embed-8b', reranker: 'qwen3-rerank-0.6b' }))
  expect(await screen.findByText('Search model saved.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Save search model' })).toBeDisabled()
})

test('Given retrieval settings, Then no reranking control is offered', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Search and retrieval' })
  await within(section).findByRole('radiogroup', { name: 'Default search model' })
  expect(within(section).queryByRole('switch')).not.toBeInTheDocument()
  expect(within(section).queryByRole('checkbox')).not.toBeInTheDocument()
  expect(within(section).queryByText(/rerank/i)).not.toBeInTheDocument()
})

test('Given retrieval settings fail to load, Then the section explains it inline and the chat defaults still work', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': () => json({ code: 'NOT_IMPLEMENTED', message: 'Search settings are not available yet.' }, 501) })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Search and retrieval' })
  expect(await within(section).findByRole('alert')).toHaveTextContent('Search settings are not available yet.')
  expect(within(section).getByRole('button', { name: 'Try again' })).toBeEnabled()
  expect(await screen.findByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked()
})
