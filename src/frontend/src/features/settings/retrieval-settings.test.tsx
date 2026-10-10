// Library and search (ARA-075, ARA-091, ARA-109): the one library-wide search index model and reranking.
// The search index switch asks first; reranking saves as soon as it changes.
import { screen, waitFor, within } from '@testing-library/react'
import type { EmbeddingProfile, Model, Reranker, RetrievalSettings } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

const luna: Model = { kind: 'chat', key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'available', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 1_050_000 }
const openai: EmbeddingProfile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null, price_per_million: 0.13, description: 'OpenAI’s most capable search model, in English and other languages.' }
const small: EmbeddingProfile = { ...openai, key: 'openai-3-small', model_id: 'text-embedding-3-small', display_name: 'OpenAI text-embedding-3-small', dimensions: 1536, price_per_million: 0.02, description: 'A smaller model: cheaper to index, less capable than the large one.' }
const qwen4b: EmbeddingProfile = { key: 'qwen3-embed-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', dimensions: 2560, status: 'unavailable', unavailable_reason: 'Download Qwen3 Embedding 4B in Settings', local_model_key: 'qwen3-embedding-4b', price_per_million: 0 }
const qwen8b: EmbeddingProfile = { ...qwen4b, key: 'qwen3-embed-8b', model_id: 'qwen3-embedding:8b', display_name: 'Qwen3 Embedding 8B', dimensions: 4096, unavailable_reason: 'Download Qwen3 Embedding 8B in Settings', local_model_key: 'qwen3-embedding-8b' }
const profiles = { items: [openai, small, qwen4b, qwen8b], default_profile: openai.key }
const saved: RetrievalSettings = { embedding_profile: openai.key, reranker: 'openai-gpt-6-luna' }
const estimate = { profile: 'openai-3-small', papers: 12, tokens: 481234, price_per_million: 0.02, estimated_cost_usd: 0.0096 }
const base = { 'GET /retrieval/reindex-estimate': estimate, 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'GET /retrieval/profiles': profiles }
afterEach(() => vi.unstubAllGlobals())
// Local model tests run with open models on, as the server reports them (ARA-090).
const openModels = { 'GET /features': { open_models: true } }
const puts = (calls: { method: string; path: string; body: unknown }[]) => calls.filter((call) => call.method === 'PUT' && call.path === '/retrieval/settings').map((call) => call.body)

test('Given four search index models with OpenAI large saved, Then Library and search lists them with large chosen and what each costs to index', async () => {
  mockApi({ ...openModels, ...base, 'GET /retrieval/settings': saved })
  renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Search index' })
  const choices = await within(section).findByRole('radiogroup', { name: 'Search index model' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['openai-3-large', 'openai-3-small', 'qwen3-embed-4b', 'qwen3-embed-8b'])
  // Each choice is titled by the model's own name, as on the Models page (ARA-109c).
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toBeChecked()
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toHaveAccessibleDescription('OpenAI’s most capable search model, in English and other languages. Indexing costs $0.13 per million tokens, about 750,000 words.')
  expect(within(choices).getByRole('radio', { name: 'OpenAI text-embedding-3-small' })).toHaveAccessibleDescription('A smaller model: cheaper to index, less capable than the large one. Indexing costs $0.02 per million tokens, about 750,000 words.')
  expect(within(section).queryByText(/Higher quality|Lower cost/)).not.toBeInTheDocument()
  expect(section).toHaveAccessibleDescription('For each paper, ara builds a semantic search index with an embedding model. It finds the parts of the paper related to the meaning of your question. Switching models reads every paper again in the background, and each paper keeps its current index until the new one is ready.')
})

test('Given Qwen 4B is not downloaded, Then its reason links to Open models and choosing it still asks first', async () => {
  mockApi({ ...openModels, ...base, 'GET /retrieval/settings': saved })
  const { user } = renderApp('/?settings=library')
  const qwen = await screen.findByRole('radio', { name: 'Qwen3 Embedding 4B' })
  expect(qwen).toHaveAccessibleDescription(/Download Qwen3 Embedding 4B in Settings/)
  const option = qwen.closest('label') as HTMLElement
  expect(within(option).getByRole('link', { name: 'Go to Open models' })).toHaveAttribute('href', '/?settings=open-models#local-models')
  expect(qwen).toBeEnabled()
  await user.click(qwen)
  expect(await screen.findByRole('alertdialog', { name: 'Rebuild the search index?' })).toBeVisible()
})

test('Given a new search index model, When it is chosen, Then a dialog says what rebuilding means and nothing is sent until confirmed', async () => {
  // Saving the search index model must not overwrite the stored reranker choice.
  const stored: RetrievalSettings = { ...saved, reranker: 'qwen3-rerank-0.6b' }
  const { calls } = mockApi({ ...openModels, ...base, 'GET /retrieval/settings': stored, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Search index' })
  await user.click(await within(section).findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Rebuild the search index?' })
  expect(await within(dialog).findByText('Switching the search index to “OpenAI text-embedding-3-small” reads all 12 papers in your library again in the background: about 480,000 tokens, roughly 360,000 words.')).toBeVisible()
  expect(within(dialog).queryByText(/^Model:/)).not.toBeInTheDocument()
  expect(within(dialog).getByText('Estimated cost: less than $0.01.')).toBeVisible()
  expect(within(dialog).getByText('Questions keep working while it runs: each paper keeps its current index until its new one is ready.')).toBeVisible()
  expect(puts(calls)).toEqual([])
  await user.click(within(dialog).getByRole('button', { name: 'Rebuild index' }))
  await waitFor(() => expect(puts(calls)).toEqual([{ embedding_profile: 'openai-3-small', reranker: 'qwen3-rerank-0.6b' }]))
  expect(calls.find((call) => call.path === '/retrieval/reindex-estimate')?.url.searchParams.get('profile')).toBe('openai-3-small')
  expect(await within(section).findByText('Rebuilding in the background')).toBeVisible()
  expect(within(section).getByRole('radio', { name: 'OpenAI text-embedding-3-small' })).toBeChecked()
})

test('Given the rebuild dialog, When Cancel is pressed, Then nothing is saved and the saved model stays chosen', async () => {
  const { calls } = mockApi({ ...base, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=library')
  await user.click(await screen.findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  expect(puts(calls)).toEqual([])
  expect(screen.getByRole('radio', { name: 'OpenAI text-embedding-3-large' })).toBeChecked()
  expect(screen.getByRole('radio', { name: 'OpenAI text-embedding-3-small' })).not.toBeChecked()
  expect(screen.getByRole('dialog', { name: 'Settings' })).toBeVisible()
})

test('Given an estimate, When the rebuild dialog opens, Then the words come from the same rounded token count', async () => {
  // 13,449 tokens reads "about 13,000"; three-quarters of that is 9,750, so "roughly 9,800 words", never 10,000 from the raw count.
  mockApi({ ...base, 'GET /retrieval/reindex-estimate': { ...estimate, papers: 2, tokens: 13_449 }, 'GET /retrieval/settings': saved })
  const { user } = renderApp('/?settings=library')
  await user.click(await screen.findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Rebuild the search index?' })
  expect(await within(dialog).findByText(/about 13,000 tokens, roughly 9,800 words\.$/)).toBeVisible()
})

test('Given an empty library, When a new model is chosen, Then the dialog says there is nothing to rebuild yet', async () => {
  mockApi({ ...base, 'GET /retrieval/reindex-estimate': { ...estimate, papers: 0, tokens: 0, estimated_cost_usd: 0 }, 'GET /retrieval/settings': saved })
  const { user } = renderApp('/?settings=library')
  await user.click(await screen.findByRole('radio', { name: 'OpenAI text-embedding-3-small' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Switch the search index model?' })
  expect(await within(dialog).findByText('Your library has no papers yet, so there is nothing to rebuild. New papers will be indexed with “OpenAI text-embedding-3-small”.')).toBeVisible()
  expect(within(dialog).getByRole('button', { name: 'Switch model' })).toBeEnabled()
})

// Reranker profiles come from the server's catalog (ARA-074); the UI renders whatever it lists.
const hostedRerank: Reranker = { key: 'openai-gpt-6-luna', provider: 'openai', model_id: 'gpt-6-luna', display_name: 'OpenAI GPT-6 Luna', status: 'available', unavailable_reason: null, local_model_key: null, candidates: 40, price_per_million: 0.1, description: 'Adds about 2 to 3 seconds and $0.004 to each question.' }
const localRerank: Reranker = { key: 'qwen3-rerank-0.6b', provider: 'ollama', model_id: 'dengcao/Qwen3-Reranker-0.6B:F16', display_name: 'Qwen3 Reranker 0.6B', status: 'unavailable', unavailable_reason: 'Download Qwen3 Reranker 0.6B in Settings.', local_model_key: 'qwen3-reranker-0.6b', candidates: 15, price_per_million: 0, description: 'Private, but adds about 10 seconds to each question.' }
const withRerankers = { ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank, localRerank] } }
const hostedOnly = { ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank] } }

test('Given one hosted reranker turned on, Then Reordering by relevance is a switch that says what it improves, what it costs, what off means and, secondarily, which model does it', async () => {
  mockApi({ ...hostedOnly, 'GET /retrieval/settings': saved })
  renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Reordering by relevance' })
  const toggle = await within(section).findByRole('switch', { name: 'Reordering by relevance' })
  expect(toggle).toBeChecked()
  expect(section).toHaveAccessibleDescription('After search, a second model reads the passages most likely to answer your question and reorders them by how well they answer it. The model that writes the answer then works from the top of that order, so it cites stronger evidence. Adds about 2 to 3 seconds and $0.004 to each question. When off, the answer works from the top of search’s own order.')
  expect(within(section).getByText('Runs on OpenAI GPT-6 Luna, separate from the model that answers.')).toHaveClass('text-xs')
  expect(within(section).queryByRole('radiogroup')).not.toBeInTheDocument()
  expect(within(section).queryByText('gpt-6-luna')).not.toBeInTheDocument()
})

test('Given reranking is on, When it is switched off, Then it saves at once with reranker null and no rebuild dialog', async () => {
  const { calls } = mockApi({ ...hostedOnly, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Reordering by relevance' })
  await user.click(await within(section).findByRole('switch', { name: 'Reordering by relevance' }))
  await waitFor(() => expect(puts(calls)).toEqual([{ embedding_profile: 'openai-3-large', reranker: null }]))
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(await within(section).findByText('Saved')).toBeVisible()
  expect(within(section).getByRole('switch', { name: 'Reordering by relevance' })).not.toBeChecked()
})

test('Given reranking saved off, When it is switched on, Then the first available reranker is saved', async () => {
  const { calls } = mockApi({ ...hostedOnly, 'GET /retrieval/settings': { ...saved, reranker: null }, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=library')
  const toggle = await screen.findByRole('switch', { name: 'Reordering by relevance' })
  expect(toggle).not.toBeChecked()
  await user.click(toggle)
  await waitFor(() => expect(puts(calls)).toEqual([{ embedding_profile: 'openai-3-large', reranker: 'openai-gpt-6-luna' }]))
})

test('Given open models with a local reranker that is not installed, Then a list offers each reranker and the local one links to Open models', async () => {
  mockApi({ ...openModels, ...withRerankers, 'GET /retrieval/settings': saved })
  renderApp('/?settings=library')
  const choices = await screen.findByRole('radiogroup', { name: 'Reordering model' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['openai-gpt-6-luna', 'qwen3-rerank-0.6b'])
  expect(within(choices).getByRole('radio', { name: 'OpenAI GPT-6 Luna' })).toBeChecked()
  const local = within(choices).getByRole('radio', { name: 'Qwen3 Reranker 0.6B' })
  expect(local).toBeDisabled()
  expect(local).toHaveAccessibleDescription(/^Private, but adds about 10 seconds to each question\. Download Qwen3 Reranker 0\.6B in Settings\./)
  expect(within(choices).getByRole('radio', { name: 'OpenAI GPT-6 Luna' })).toHaveAccessibleDescription('Adds about 2 to 3 seconds and $0.004 to each question.')
  expect(within(local.closest('label') as HTMLElement).getByRole('link', { name: 'Go to Open models' })).toHaveAttribute('href', '/?settings=open-models#local-models')
})

test('Given an installed local reranker, When it is chosen, Then PUT sends its key with the saved search index model', async () => {
  const { calls } = mockApi({ ...openModels, ...base, 'GET /retrieval/profiles': { ...profiles, rerankers: [hostedRerank, { ...localRerank, status: 'available', unavailable_reason: null }] }, 'GET /retrieval/settings': saved, 'PUT /retrieval/settings': ({ body }) => json(body) })
  const { user } = renderApp('/?settings=library')
  await user.click(await screen.findByRole('radio', { name: 'Qwen3 Reranker 0.6B' }))
  await waitFor(() => expect(puts(calls)).toEqual([{ embedding_profile: 'openai-3-large', reranker: 'qwen3-rerank-0.6b' }]))
  expect(screen.getByRole('radio', { name: 'Qwen3 Reranker 0.6B' })).toBeChecked()
})

test('Given a server that lists no rerankers, Then reranking cannot be turned on and says why', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': { ...saved, reranker: null } })
  renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Reordering by relevance' })
  expect(await within(section).findByRole('switch', { name: 'Reordering by relevance' })).toBeDisabled()
  expect(within(section).getByText('This server offers no model for reordering.')).toBeVisible()
})

test('Given search settings fail to load, Then Library and search explains it in place and the other categories still work', async () => {
  mockApi({ ...base, 'GET /retrieval/settings': () => json({ code: 'NOT_IMPLEMENTED', message: 'Search settings are not available yet.' }, 501) })
  const { user } = renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Search index' })
  expect(await within(section).findByRole('alert')).toHaveTextContent('Search settings are not available yet.')
  expect(within(section).getByRole('button', { name: 'Try again' })).toBeEnabled()
  await user.click(screen.getByRole('tab', { name: 'Models' }))
  expect(await within(await screen.findByRole('radiogroup', { name: 'Default model' })).findByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked()
})

test('Given Library and search, Then a plain explainer leads, each setting is tied to it with help text, and answering comes before paper details', async () => {
  mockApi({ ...hostedOnly, 'GET /retrieval/settings': saved, 'GET /metadata/settings': { source: 'openalex' } })
  renderApp('/?settings=library')
  const panel = await screen.findByRole('tabpanel', { name: 'Library and search' })
  expect(within(panel).getByText('When you ask about your papers, search looks for the passages that match your question, by its meaning and by its words. Reordering can then sort those passages by how well they answer it. The model that writes the answer reads the top passages in the order they appear in each paper, and cites the page each one comes from.')).toBeVisible()
  await within(panel).findByRole('switch', { name: 'Reordering by relevance' })
  const regions = within(panel).getAllByRole('region')
  expect(regions.map((region) => region.getAttribute('aria-label') ?? document.getElementById(region.getAttribute('aria-labelledby') ?? '')?.textContent)).toEqual(['Search index', 'Reordering by relevance', 'Paper details'])
  for (const region of regions) expect(region).toHaveAccessibleDescription(/\w{3,}.*\./)
  expect(regions[0]).toHaveAccessibleDescription(/^For each paper, ara builds a semantic search index/)
  expect(regions[2]).toHaveAccessibleDescription(/^When you upload a PDF, its title, authors, year, venue and abstract are first read from the PDF itself\./)
})
