// Paper "Search index" in the ⓘ dialog (ARA-075, ARA-091, ARA-101): the library model, this paper's index state and rebuilds.
import { act, screen, waitFor, within } from '@testing-library/react'
import type { EmbeddingProfile, Paper, PaperRetrieval, RetrievalIndex } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { SearchIndexPanel } from './SearchIndexPanel'

const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'doc-1', metadata_provenance: {} }
const openai: EmbeddingProfile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null, price_per_million: 0.13 }
const qwen4b: EmbeddingProfile = { key: 'qwen3-embed-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', dimensions: 2560, status: 'available', unavailable_reason: null, local_model_key: 'qwen3-embedding-4b', price_per_million: 0 }
const qwen8b: EmbeddingProfile = { ...qwen4b, key: 'qwen3-embed-8b', model_id: 'qwen3-embedding:8b', display_name: 'Qwen3 Embedding 8B', status: 'unavailable', unavailable_reason: 'Download Qwen3 Embedding 8B in Settings', local_model_key: 'qwen3-embedding-8b' }
const profiles = { items: [openai, qwen4b, qwen8b], default_profile: openai.key }
const index = (overrides: Partial<RetrievalIndex> = {}): RetrievalIndex => ({ profile: openai.key, state: 'ready', embedded: 212, total: 212, updated_at: '2026-10-09T12:00:00Z', error: null, ...overrides })
const retrieval = (overrides: Partial<PaperRetrieval> = {}): PaperRetrieval => ({ paper_id: 'p1', document_id: 'doc-1', effective_profile: openai.key, parser: 'pymupdf4llm', chunk_count: 212, section_count: 14, mode: 'hybrid', mode_note: null, indexes: [index()], ...overrides })
const building = retrieval({ mode: 'keyword', indexes: [index({ state: 'embedding', embedded: 89, total: 212 })] })
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
// Local model tests run with open models on, as the server reports them (ARA-090).
const openModels = { 'GET /features': { open_models: true } }

function mount(value: Paper = paper) { return renderWithProviders(<SearchIndexPanel paperId={value.id} />) }

test('Given a ready index on the default model, Then one plain sentence names the passages and the model, with no status pill', async () => {
  mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': retrieval() })
  mount()
  const panel = screen.getByRole('region', { name: 'Search index' })
  expect(await within(panel).findByText('Searching 212 passages in 14 sections with OpenAI text-embedding-3-large.')).toBeVisible()
  // The model is named once, a ready index needs no pill, and the user has asked for no middle dots.
  expect(within(panel).queryByText('text-embedding-3-large')).not.toBeInTheDocument()
  expect(within(panel).queryByText('Ready')).not.toBeInTheDocument()
  expect(panel).not.toHaveTextContent('·')
  expect(within(panel).queryByRole('progressbar')).not.toBeInTheDocument()
  // One library-wide model (ARA-091): there is no per-paper choice.
  expect(within(panel).queryByRole('button', { name: 'Change model' })).not.toBeInTheDocument()
  expect(within(panel).getByRole('button', { name: 'Rebuild index' })).toBeEnabled()
})

test('Given Rebuild index, When pressed, Then the panel polls Building until Ready', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let current = retrieval()
  const { calls } = mockApi({ ...openModels,
    'GET /retrieval/profiles': profiles,
    'GET /papers/p1/retrieval': () => json(current),
    'POST /papers/p1/retrieval/rebuild': () => { current = building; return json(current, 202) },
  })
  const { user } = mount()
  const panel = screen.getByRole('region', { name: 'Search index' })
  await user.click(await within(panel).findByRole('button', { name: 'Rebuild index' }))
  expect((calls.find((call) => call.method === 'POST')?.body as { request_id: string }).request_id).toMatch(uuid)
  expect(await within(panel).findByText('Building the index')).toBeVisible()
  expect(within(panel).getByText('42%')).toBeVisible()
  expect(within(panel).getByRole('progressbar', { name: 'Search index progress' })).toHaveAttribute('aria-valuenow', '42')
  expect(within(panel).getByText('Answers use keyword search until the index is ready.')).toBeVisible()
  expect(within(panel).getByRole('button', { name: 'Rebuild index' })).toBeDisabled()
  current = retrieval()
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  await waitFor(() => expect(within(panel).queryByText('Building the index')).not.toBeInTheDocument())
  expect(within(panel).queryByText(/keyword search/)).not.toBeInTheDocument()
  // Polling stops once nothing is building.
  const reads = calls.filter((call) => call.method === 'GET' && call.path === '/papers/p1/retrieval').length
  await act(async () => { await vi.advanceTimersByTimeAsync(4500) })
  expect(calls.filter((call) => call.method === 'GET' && call.path === '/papers/p1/retrieval')).toHaveLength(reads)
})

test('Given a failed index, Then the error shows with Rebuild, and each rebuild sends its own request id', async () => {
  const failed = retrieval({ mode: 'keyword', indexes: [index({ state: 'failed', embedded: 64, error: { code: 'EMBEDDING_FAILED', message: 'The search model stopped responding. Rebuild to try again.' } })] })
  const { calls } = mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': failed, 'POST /papers/p1/retrieval/rebuild': () => json(failed, 202) })
  const { user } = mount()
  const panel = screen.getByRole('region', { name: 'Search index' })
  expect(await within(panel).findByRole('alert')).toBeVisible()
  expect(within(panel).queryByText('Failed')).not.toBeInTheDocument()
  expect(within(panel).getByRole('alert')).toHaveTextContent('The search model stopped responding. Rebuild to try again.')
  await user.click(within(panel).getByRole('button', { name: 'Rebuild index' }))
  await waitFor(() => expect(within(panel).getByRole('button', { name: 'Rebuild index' })).toBeEnabled())
  await user.click(within(panel).getByRole('button', { name: 'Rebuild index' }))
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(2))
  const ids = calls.filter((call) => call.method === 'POST').map((call) => (call.body as { request_id: string }).request_id)
  expect(ids[0]).toMatch(uuid)
  expect(ids[1]).toMatch(uuid)
  expect(ids[0]).not.toBe(ids[1])
})

test('Given an unavailable search model, Then the panel says why in plain language', async () => {
  mockApi({
    'GET /retrieval/profiles': profiles,
    'GET /papers/p1/retrieval': retrieval({ effective_profile: qwen8b.key, mode: 'keyword', indexes: [index({ profile: qwen8b.key, state: 'unavailable', embedded: 0 })] }),
  })
  mount()
  const panel = screen.getByRole('region', { name: 'Search index' })
  expect(await within(panel).findByText('Download Qwen3 Embedding 8B in Settings')).toBeVisible()
  expect(within(panel).queryByText('Unavailable')).not.toBeInTheDocument()
  expect(within(panel).getByText('Download Qwen3 Embedding 8B in Settings')).toBeVisible()
})

test('Given a new model building while the previous index is ready, Then answers keep using the previous index', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  mockApi({
    'GET /retrieval/profiles': profiles,
    'GET /papers/p1/retrieval': retrieval({ effective_profile: qwen4b.key, mode: 'hybrid', indexes: [index(), index({ profile: qwen4b.key, state: 'queued', embedded: 0 })] }),
  })
  mount()
  const panel = screen.getByRole('region', { name: 'Search index' })
  expect(await within(panel).findByText('Building the index')).toBeVisible()
  expect(within(panel).getByText('Answers keep using the previous index until the new one is ready.')).toBeVisible()
  expect(within(panel).queryByText(/keyword search/)).not.toBeInTheDocument()
})

test('Given the index cannot be loaded, Then the panel explains it inline with Try again', async () => {
  mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': () => json({ code: 'NOT_IMPLEMENTED', message: 'Search index details are not available yet.' }, 501) })
  mount()
  const panel = screen.getByRole('region', { name: 'Search index' })
  expect(await within(panel).findByRole('alert')).toHaveTextContent('Search index details are not available yet.')
  expect(within(panel).getByRole('button', { name: 'Try again' })).toBeEnabled()
})
