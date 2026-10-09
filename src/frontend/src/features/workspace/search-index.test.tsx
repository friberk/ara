// Paper "Search index" panel in Details (ARA-075): which model a paper searches with, its index state, and changes.
import { act, screen, waitFor, within } from '@testing-library/react'
import type { EmbeddingProfile, Paper, PaperRetrieval, RetrievalIndex } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { DetailsPanel } from './DetailsPanel'

const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'doc-1', metadata_provenance: {} }
const openai: EmbeddingProfile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null }
const qwen4b: EmbeddingProfile = { key: 'qwen3-embed-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', dimensions: 2560, status: 'available', unavailable_reason: null, local_model_key: 'qwen3-embedding-4b' }
const qwen8b: EmbeddingProfile = { ...qwen4b, key: 'qwen3-embed-8b', model_id: 'qwen3-embedding:8b', display_name: 'Qwen3 Embedding 8B', status: 'unavailable', unavailable_reason: 'Download Qwen3 Embedding 8B in Settings', local_model_key: 'qwen3-embedding-8b' }
const profiles = { items: [openai, qwen4b, qwen8b], default_profile: openai.key }
const index = (overrides: Partial<RetrievalIndex> = {}): RetrievalIndex => ({ profile: openai.key, state: 'ready', embedded: 212, total: 212, updated_at: '2026-10-09T12:00:00Z', error: null, ...overrides })
const retrieval = (overrides: Partial<PaperRetrieval> = {}): PaperRetrieval => ({ paper_id: 'p1', document_id: 'doc-1', effective_profile: openai.key, source: 'default', parser: 'pymupdf4llm', chunk_count: 212, section_count: 14, mode: 'hybrid', mode_note: null, indexes: [index()], ...overrides })
const building = retrieval({ effective_profile: qwen4b.key, source: 'paper', mode: 'keyword', indexes: [index({ profile: qwen4b.key, state: 'embedding', embedded: 89, total: 212 })] })
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

function mount(value: Paper = paper) { return renderWithProviders(<DetailsPanel paper={value} onOpenPdf={() => {}} />) }
async function expand(user: ReturnType<typeof mount>['user']) {
  await user.click(screen.getByRole('button', { name: /^Search index/ }))
  return screen.getByRole('region', { name: /^Search index/ })
}

test('Given a ready paper, Then Details ends with a collapsed advanced Search index that loads nothing until opened', () => {
  const { calls } = mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': retrieval() })
  mount()
  const trigger = screen.getByRole('button', { name: /^Search index/ })
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  expect(within(trigger).getByText('Advanced')).toHaveClass('text-muted-foreground')
  expect(screen.queryByText(/Searching with/)).not.toBeInTheDocument()
  expect(calls.some((call) => call.path.includes('retrieval'))).toBe(false)
})

test('Given a metadata-only paper, Then there is no Search index to show', () => {
  mockApi({})
  mount({ ...paper, document_status: 'metadata_only', active_document_id: null })
  expect(screen.queryByRole('button', { name: /^Search index/ })).not.toBeInTheDocument()
})

test('Given a ready index on the default model, When expanded, Then it names the model, its state and the counts', async () => {
  mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': retrieval() })
  const { user } = mount()
  const panel = await expand(user)
  expect(await within(panel).findByText('OpenAI text-embedding-3-large')).toBeVisible()
  expect(within(panel).getByText(/Searching with/)).toHaveTextContent('Searching with OpenAI text-embedding-3-large (default)')
  expect(within(panel).getByText('text-embedding-3-large')).toHaveClass('font-mono')
  expect(within(panel).getByText('Ready')).toBeVisible()
  expect(within(panel).getByText('212 passages · 14 sections')).toBeVisible()
  expect(within(panel).queryByRole('progressbar')).not.toBeInTheDocument()
  expect(within(panel).getByRole('button', { name: 'Change model' })).toBeEnabled()
  expect(within(panel).getByRole('button', { name: 'Rebuild index' })).toBeEnabled()
})

test('Given Change model to Qwen 4B, When saved, Then PUT names the profile and the panel polls Building until Ready', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let current = retrieval()
  const { calls } = mockApi({
    'GET /retrieval/profiles': profiles,
    'GET /papers/p1/retrieval': () => json(current),
    'PUT /papers/p1/retrieval': () => { current = building; return json(current) },
  })
  const { user } = mount()
  const panel = await expand(user)
  await user.click(await within(panel).findByRole('button', { name: 'Change model' }))
  const dialog = await screen.findByRole('dialog', { name: 'Search model for this paper' })
  const choices = within(dialog).getByRole('radiogroup', { name: 'Search model' })
  expect(within(choices).getByRole('radio', { name: 'Use default' })).toBeChecked()
  await user.click(within(choices).getByRole('radio', { name: 'Qwen3 Embedding 4B' }))
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  const put = calls.find((call) => call.method === 'PUT')?.body as { profile: string | null; request_id: string }
  expect(put.profile).toBe('qwen3-embed-4b')
  expect(put.request_id).toMatch(uuid)
  expect(await within(panel).findByText(/Searching with/)).toHaveTextContent('Searching with Qwen3 Embedding 4B (this paper)')
  expect(within(panel).getByText('Building')).toBeVisible()
  expect(within(panel).getByText('42%')).toBeVisible()
  expect(within(panel).getByRole('progressbar', { name: 'Search index progress' })).toHaveAttribute('aria-valuenow', '42')
  expect(within(panel).getByText('Answers use keyword search until the index is ready.')).toBeVisible()
  expect(within(panel).getByRole('button', { name: 'Rebuild index' })).toBeDisabled()
  current = retrieval({ effective_profile: qwen4b.key, source: 'paper', indexes: [index({ profile: qwen4b.key })] })
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  expect(await within(panel).findByText('Ready')).toBeVisible()
  expect(within(panel).queryByText(/keyword search/)).not.toBeInTheDocument()
  // Polling stops once nothing is building.
  const reads = calls.filter((call) => call.method === 'GET' && call.path === '/papers/p1/retrieval').length
  await act(async () => { await vi.advanceTimersByTimeAsync(4500) })
  expect(calls.filter((call) => call.method === 'GET' && call.path === '/papers/p1/retrieval')).toHaveLength(reads)
})

test('Given a per-paper model, When Use default is saved, Then PUT sends a null profile', async () => {
  const { calls } = mockApi({
    'GET /retrieval/profiles': profiles,
    'GET /papers/p1/retrieval': retrieval({ effective_profile: qwen4b.key, source: 'paper', indexes: [index({ profile: qwen4b.key })] }),
    'PUT /papers/p1/retrieval': retrieval(),
  })
  const { user } = mount()
  const panel = await expand(user)
  expect(await within(panel).findByText(/Searching with/)).toHaveTextContent('Searching with Qwen3 Embedding 4B (this paper)')
  await user.click(within(panel).getByRole('button', { name: 'Change model' }))
  const dialog = await screen.findByRole('dialog', { name: 'Search model for this paper' })
  expect(within(dialog).getByRole('radio', { name: 'Qwen3 Embedding 4B' })).toBeChecked()
  expect(within(dialog).getByRole('radio', { name: 'Use default' })).toHaveAccessibleDescription(/OpenAI text-embedding-3-large/)
  await user.click(within(dialog).getByRole('radio', { name: 'Use default' }))
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ profile: null, request_id: expect.stringMatching(uuid) }))
  await waitFor(() => expect(within(panel).getByText(/Searching with/)).toHaveTextContent('Searching with OpenAI text-embedding-3-large (default)'))
})

test('Given a failed index, Then the error shows with Rebuild, and each rebuild sends its own request id', async () => {
  const failed = retrieval({ mode: 'keyword', indexes: [index({ state: 'failed', embedded: 64, error: { code: 'EMBEDDING_FAILED', message: 'The search model stopped responding. Rebuild to try again.' } })] })
  const { calls } = mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': failed, 'POST /papers/p1/retrieval/rebuild': () => json(failed, 202) })
  const { user } = mount()
  const panel = await expand(user)
  expect(await within(panel).findByText('Failed')).toBeVisible()
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
    'GET /papers/p1/retrieval': retrieval({ effective_profile: qwen8b.key, source: 'paper', mode: 'keyword', indexes: [index({ profile: qwen8b.key, state: 'unavailable', embedded: 0 })] }),
  })
  const { user } = mount()
  const panel = await expand(user)
  expect(await within(panel).findByText('Unavailable')).toBeVisible()
  expect(within(panel).getByText('Download Qwen3 Embedding 8B in Settings')).toBeVisible()
})

test('Given a new model building while the previous index is ready, Then answers keep using the previous index', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  mockApi({
    'GET /retrieval/profiles': profiles,
    'GET /papers/p1/retrieval': retrieval({ effective_profile: qwen4b.key, source: 'paper', mode: 'hybrid', indexes: [index(), index({ profile: qwen4b.key, state: 'queued', embedded: 0 })] }),
  })
  const { user } = mount()
  const panel = await expand(user)
  expect(await within(panel).findByText('Building')).toBeVisible()
  expect(within(panel).getByText('Answers keep using the previous index until the new one is ready.')).toBeVisible()
  expect(within(panel).queryByText(/keyword search/)).not.toBeInTheDocument()
})

test('Given the index cannot be loaded, Then the panel explains it inline with Try again', async () => {
  mockApi({ 'GET /retrieval/profiles': profiles, 'GET /papers/p1/retrieval': () => json({ code: 'NOT_IMPLEMENTED', message: 'Search index details are not available yet.' }, 501) })
  const { user } = mount()
  const panel = await expand(user)
  expect(await within(panel).findByRole('alert')).toHaveTextContent('Search index details are not available yet.')
  expect(within(panel).getByRole('button', { name: 'Try again' })).toBeEnabled()
})
