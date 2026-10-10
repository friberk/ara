// Search and retrieval settings (ARA-075, ARA-091): the one library-wide search model, separate from the chat model defaults.
import { screen, waitFor, within } from '@testing-library/react'
import type { EmbeddingProfile, Reranker, RetrievalSettings } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

const luna = { kind: 'chat' as const, key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const openai: EmbeddingProfile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null, price_per_million: 0.13 }
const small: EmbeddingProfile = { ...openai, key: 'openai-3-small', model_id: 'text-embedding-3-small', display_name: 'OpenAI text-embedding-3-small', dimensions: 1536, price_per_million: 0.02 }
const qwen4b: EmbeddingProfile = { key: 'qwen3-embed-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', dimensions: 2560, status: 'unavailable', unavailable_reason: 'Download Qwen3 Embedding 4B in Settings', local_model_key: 'qwen3-embedding-4b', price_per_million: 0 }
const qwen8b: EmbeddingProfile = { ...qwen4b, key: 'qwen3-embed-8b', model_id: 'qwen3-embedding:8b', display_name: 'Qwen3 Embedding 8B', dimensions: 4096, unavailable_reason: 'Download Qwen3 Embedding 8B in Settings', local_model_key: 'qwen3-embedding-8b' }
const profiles = { items: [openai, small, qwen4b, qwen8b], default_profile: openai.key }
const saved: RetrievalSettings = { embedding_profile: openai.key, reranker: 'openai-gpt-6-luna' }
const estimate = { profile: 'openai-3-small', papers: 12, tokens: 480000, price_per_million: 0.02, estimated_cost_usd: 0.0096 }
const base = { 'GET /retrieval/reindex-estimate': estimate, 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'GET /retrieval/profiles': profiles }
afterEach(() => vi.unstubAllGlobals())

test('Given four search models with OpenAI large saved, Then Settings lists them with large chosen, exact ids in mono and each price', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Search and retrieval' })
  const choices = await within(section).findByRole('radiogroup', { name: 'Search model' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['openai-3-large', 'openai-3-small', 'qwen3-embed-4b', 'qwen3-embed-8b'])
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toBeChecked()
  expect(within(choices).getByText('text-embedding-3-large')).toHaveClass('font-mono')
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toHaveAccessibleDescription(/\$0\.13 per million tokens/)
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-small' })).toHaveAccessibleDescription(/\$0\.02 per million tokens/)
  expect(within(section).getByText(/One model searches the whole library/)).toBeVisible()
  expect(within(section).getByRole('button', { name: 'Save search settings' })).toBeDisabled()
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
  expect(screen.getByRole('button', { name: 'Save search settings' })).toBeEnabled()
})

test('Given a new model, When Save is pressed, Then a dialog warns the whole library is re-embedded and nothing is sent until confirmed', async () => {
  // Saving the search model must not overwrite the stored reranker choice.
  const stored: RetrievalSettings = { ...saved, reranker: 'qwen3-rerank-0.6b' }
  const { calls } = mockApi({ ...base, 'GET /retrieval/settings': stored, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Re-embed the whole library?' })
  expect(await within(dialog).findByText(/Switching to OpenAI text-embedding-3-small re-embeds your whole library in the background: 12 papers, about 480,000 tokens\./)).toBeVisible()
  expect(within(dialog).getByText('Estimated cost: less than $0.01.')).toBeVisible()
  expect(within(dialog).getByText(/Questions keep working meanwhile/)).toBeVisible()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
  await user.click(within(dialog).getByRole('button', { name: 'Re-embed library' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/retrieval/settings')?.body).toEqual({ embedding_profile: 'openai-3-small', reranker: 'qwen3-rerank-0.6b' }))
  expect(calls.find((call) => call.path === '/retrieval/reindex-estimate')?.url.searchParams.get('profile')).toBe('openai-3-small')
  expect(await screen.findByText('Search settings saved.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Save search settings' })).toBeDisabled()
})

test('Given the confirmation dialog, When Cancel is pressed, Then nothing is saved and the choice stays', async () => {
  const { calls } = mockApi({ ...base, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
  expect(screen.getByRole('radio', { name: 'OpenAI text-embedding-3-small' })).toBeChecked()
})

test('Given an empty library, When a new model is saved, Then the dialog says there is nothing to re-embed yet', async () => {
  mockApi({ ...base, 'GET /retrieval/reindex-estimate': { ...estimate, papers: 0, tokens: 0, estimated_cost_usd: 0 }, 'GET /retrieval/settings': saved })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  expect(await within(await screen.findByRole('alertdialog')).findByText(/no papers to re-embed yet/)).toBeVisible()
})

test('Given only the reranker changed, When Save is pressed, Then it saves at once without the re-embed dialog', async () => {
  const { calls } = mockApi({ ...withRerankers, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('radio', { name: 'Off' }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true))
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
})

// Reranker profiles come from the server's catalog (ARA-074); the UI renders whatever it lists, plus Off.
const hostedRerank: Reranker = { key: 'openai-gpt-6-luna', provider: 'openai', model_id: 'gpt-6-luna', display_name: 'GPT-6 Luna', status: 'available', unavailable_reason: null, local_model_key: null, candidates: 30 }
const localRerank: Reranker = { key: 'qwen3-rerank-0.6b', provider: 'ollama', model_id: 'dengcao/Qwen3-Reranker-0.6B:F16', display_name: 'Qwen3 Reranker 0.6B', status: 'unavailable', unavailable_reason: 'Download Qwen3 Reranker 0.6B in Settings.', local_model_key: 'qwen3-reranker-0.6b', candidates: 15 }
const withRerankers = { ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank, localRerank] } }

test('Given catalog rerankers, Then Rerank results lists each with its id and what it costs, plus Off, with the saved one chosen', async () => {
  mockApi({ ...withRerankers, 'GET /retrieval/settings': saved })
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
  mockApi({ ...withRerankers, 'GET /retrieval/settings': saved })
  renderApp('/settings')
  const local = await screen.findByRole('radio', { name: 'Qwen3 Reranker 0.6B' })
  expect(local).toBeDisabled()
  expect(local).toHaveAccessibleDescription(/^dengcao\/Qwen3-Reranker-0\.6B:F16 Private\. Adds about 10 seconds to each answer\. Download Qwen3 Reranker 0\.6B in Settings\./)
  expect(within(local.closest('label') as HTMLElement).getByRole('link', { name: 'Go to Local models' })).toHaveAttribute('href', '/settings#local-models')
})

test('Given an installed local reranker, When it is chosen and saved, Then PUT sends its key with the saved search model', async () => {
  const { calls } = mockApi({ ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank, { ...localRerank, status: 'available', unavailable_reason: null }] }, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
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
