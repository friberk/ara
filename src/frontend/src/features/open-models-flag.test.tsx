// Open models are experimental and off unless the server reports them on (ARA-090).
import { screen, within } from '@testing-library/react'
import type { EmbeddingProfile, Model, ModelInstallation, PaperRetrieval, Reranker } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ModelSwitcher } from '@/components/composer/ModelSwitcher'
import { SearchIndexPanel } from '@/features/workspace/SearchIndexPanel'
import { mockApi } from '@/test/fetch-routes'
import { renderApp, renderWithProviders } from '@/test/render'

const off = { 'GET /features': { open_models: false } }
const on = { 'GET /features': { open_models: true } }
const disabled = 'Open models are turned off on this server. Choose a hosted model.'
const searchReason = 'Open models are turned off on this server. Choose a hosted search model.'
const luna: Model = { kind: 'chat', key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const installation: ModelInstallation = { state: 'ready', weights_present: true, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 0, total_bytes: null, job_id: null, digest: null, updated_at: null, error: null }
// What a server that still lists local models would send; the flag decides whether they are shown.
const local: Model = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'IFM K2 Horizon 7B', status: 'available', reasoning_efforts: ['default'], context_window: 8192, installation }
// A saved local default, as the flag-off server reports it.
const savedLocal: Model = { ...local, status: 'unavailable', installation: null, unavailable_code: 'OPEN_MODELS_DISABLED', unavailable_reason: disabled }
const openai: EmbeddingProfile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null, price_per_million: 0.13 }
const qwen: EmbeddingProfile = { key: 'qwen3-embed-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', dimensions: 2560, status: 'available', unavailable_reason: null, local_model_key: 'qwen3-embedding-4b', price_per_million: 0 }
const hostedReranker: Reranker = { key: 'openai-gpt-6-luna', provider: 'openai', model_id: 'gpt-6-luna', display_name: 'OpenAI GPT-6 Luna', status: 'available', unavailable_reason: null, local_model_key: null, candidates: 40 }
const localReranker: Reranker = { key: 'qwen3-rerank-0.6b', provider: 'ollama', model_id: 'fanyx/Qwen3-Reranker-0.6B-Q8_0', display_name: 'Qwen3 Reranker 0.6B (local)', status: 'available', unavailable_reason: null, local_model_key: 'qwen3-reranker-0.6b', candidates: 12 }
const hostedDefaults = { default_model: luna.key, reasoning_effort: 'low' }
afterEach(() => vi.unstubAllGlobals())

function Selection() { const { settings } = useGenerationSettings(); return <output aria-label="Selection">{`${settings.model}/${settings.reasoning_effort}`}</output> }
function mountSwitcher() {
  return renderWithProviders(<TooltipProvider><GenerationSettingsProvider><ModelSwitcher purpose="chat" /><Selection /></GenerationSettingsProvider></TooltipProvider>)
}

test('Given open models off, When Settings opens, Then no local model, Local models section or local search option appears', async () => {
  mockApi({
    ...off, 'GET /models': { items: [luna, local] }, 'GET /settings': hostedDefaults,
    'GET /retrieval/profiles': { items: [openai, qwen], default_profile: openai.key, rerankers: [hostedReranker, localReranker] },
    'GET /retrieval/settings': { embedding_profile: openai.key, reranker: hostedReranker.key },
  })
  renderApp('/settings')
  expect(await screen.findByRole('radio', { name: luna.display_name })).toBeVisible()
  const search = await screen.findByRole('radiogroup', { name: 'Search model' })
  expect(within(search).getByRole('radio', { name: openai.display_name })).toBeChecked()
  expect(screen.queryByRole('radio', { name: local.display_name })).not.toBeInTheDocument()
  expect(screen.queryByRole('radio', { name: qwen.display_name })).not.toBeInTheDocument()
  expect(screen.queryByRole('radio', { name: localReranker.display_name })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Local models' })).not.toBeInTheDocument()
  expect(screen.queryByText(/Private\./)).not.toBeInTheDocument()
})

test('Given open models on, When Settings opens, Then the local controls return unchanged', async () => {
  mockApi({ ...on, 'GET /models': { items: [luna, local] }, 'GET /settings': hostedDefaults })
  renderApp('/settings')
  expect(await screen.findByRole('heading', { name: 'Local models' })).toBeVisible()
  expect(screen.getByRole('radio', { name: local.display_name })).toBeEnabled()
})

test('Given a saved local default with open models off, Then Settings reports it unavailable and offers hosted models', async () => {
  mockApi({ ...off, 'GET /models': { items: [luna, savedLocal] }, 'GET /settings': { default_model: savedLocal.key, reasoning_effort: 'default' } })
  renderApp('/settings')
  const saved = await screen.findByRole('radio', { name: savedLocal.display_name })
  expect(saved).toBeChecked()
  expect(saved).toBeDisabled()
  expect(saved).toHaveAccessibleDescription(expect.stringContaining(disabled))
  expect(screen.getByRole('radio', { name: luna.display_name })).toBeEnabled()
  expect(screen.queryByRole('heading', { name: 'Local models' })).not.toBeInTheDocument()
})

test('Given a saved local reranker and search model with open models off, Then Settings shows them unavailable without local links', async () => {
  const reason = searchReason
  mockApi({
    ...off, 'GET /models': { items: [luna] }, 'GET /settings': hostedDefaults,
    'GET /retrieval/profiles': {
      items: [openai, { ...qwen, status: 'unavailable', unavailable_reason: reason, local_model_key: null }], default_profile: qwen.key,
      rerankers: [hostedReranker, { ...localReranker, status: 'unavailable', unavailable_reason: reason, local_model_key: null }],
    },
    'GET /retrieval/settings': { embedding_profile: qwen.key, reranker: localReranker.key },
  })
  renderApp('/settings')
  const reranker = await screen.findByRole('radio', { name: localReranker.display_name })
  expect(reranker).toBeChecked()
  expect(reranker).toBeDisabled()
  const embedder = screen.getByRole('radio', { name: qwen.display_name })
  expect(embedder).toBeChecked()
  expect(embedder).toBeDisabled()
  expect(screen.getAllByText(reason)).toHaveLength(2)
  expect(screen.queryByRole('link', { name: 'Go to Local models' })).not.toBeInTheDocument()
  expect(screen.queryByText(/Private\./)).not.toBeInTheDocument()
})

test('Given open models off, When the composer model menu opens, Then only hosted models are offered', async () => {
  mockApi({ ...off, 'GET /models': { items: [luna, local] }, 'GET /settings': hostedDefaults })
  const { user } = mountSwitcher()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  expect(screen.getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual([`${luna.display_name}${luna.model_id}`])
  expect(screen.getByRole('menuitem', { name: 'Model settings' })).toHaveAttribute('href', '/settings')
})

test('Given a saved local default with open models off, Then the composer reports it and never switches to a paid model', async () => {
  mockApi({ ...off, 'GET /models': { items: [luna, savedLocal] }, 'GET /settings': { default_model: savedLocal.key, reasoning_effort: 'default' } })
  const { user } = mountSwitcher()
  await user.click(await screen.findByRole('button', { name: `Model: ${savedLocal.display_name}` }))
  expect(screen.getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual([`${luna.display_name}${luna.model_id}`])
  expect(screen.getByText(disabled)).toBeVisible()
  await user.keyboard('{Escape}')
  expect(screen.getByRole('status', { name: 'Selection' })).toHaveTextContent(`${savedLocal.key}/default`)
})

test('Given open models off, When Activity lists jobs, Then local model work and copy stay out of view', async () => {
  const base = { attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, progress: 0, available_at: '2026-10-08T10:00:00Z', created_at: '2026-10-08T10:00:00Z', updated_at: '2026-10-08T10:05:00Z' }
  mockApi({
    ...off, 'GET /models': { items: [luna] },
    'GET /jobs': { items: [{ ...base, id: 'j1', kind: 'model_download', state: 'queued', stage: 'queued', model_key: local.key }, { ...base, id: 'j2', kind: 'summary', state: 'completed', stage: 'completed', progress: 100, paper_id: 'p2', paper_title: 'Attention is all you need' }] },
  })
  renderApp('/activity')
  expect(await screen.findByRole('heading', { name: 'Paper summary' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'Model download' })).not.toBeInTheDocument()
  expect(screen.queryByText(/model downloads/)).not.toBeInTheDocument()
})

test('Given a local library search model with open models off, Then the paper’s search index explains keyword search', async () => {
  const reason = 'Open models are turned off on this server. This paper is searched by keywords until you choose a hosted search model.'
  const retrieval: PaperRetrieval = {
    paper_id: 'p1', document_id: 'doc-1', effective_profile: qwen.key, parser: 'pymupdf4llm', chunk_count: 12, section_count: 3, mode: 'keyword', mode_note: reason,
    indexes: [{ profile: qwen.key, state: 'unavailable', embedded: 12, total: 12, updated_at: null, error: { code: 'OPEN_MODELS_DISABLED', message: reason } }],
  }
  mockApi({ ...off, 'GET /retrieval/profiles': { items: [openai, { ...qwen, status: 'unavailable', unavailable_reason: searchReason, local_model_key: null }], default_profile: qwen.key }, 'GET /papers/p1/retrieval': retrieval })
  const { user } = renderWithProviders(<SearchIndexPanel paperId="p1" />)
  await user.click(screen.getByRole('button', { name: 'Advanced' }))
  expect(await screen.findByText(reason)).toBeVisible()
  expect(screen.getByText(/Searching with/)).toHaveTextContent(`Searching with ${qwen.display_name}`)
})

test('Given a saved local library model with open models off, When switching, Then only hosted models are offered and estimated', async () => {
  const small: EmbeddingProfile = { ...openai, key: 'openai-3-small', model_id: 'text-embedding-3-small', display_name: 'OpenAI text-embedding-3-small', dimensions: 1536, price_per_million: 0.02 }
  const qwen8b: EmbeddingProfile = { ...qwen, key: 'qwen3-embed-8b', display_name: 'Qwen3 Embedding 8B' }
  const { calls } = mockApi({
    ...off, 'GET /models': { items: [luna] }, 'GET /settings': hostedDefaults,
    'GET /retrieval/profiles': { items: [openai, small, { ...qwen, status: 'unavailable', unavailable_reason: searchReason, local_model_key: null }, qwen8b], default_profile: qwen.key, rerankers: [hostedReranker] },
    'GET /retrieval/settings': { embedding_profile: qwen.key, reranker: hostedReranker.key },
    'GET /retrieval/reindex-estimate': { profile: small.key, papers: 6, tokens: 120000, price_per_million: 0.02, estimated_cost_usd: 0.0024 },
  })
  const { user } = renderApp('/settings')
  const choices = await screen.findByRole('radiogroup', { name: 'Search model' })
  expect(within(choices).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual([openai.key, small.key, qwen.key])
  expect(within(choices).getByRole('radio', { name: qwen.display_name })).toBeDisabled()
  await user.click(within(choices).getByRole('radio', { name: small.display_name }))
  await user.click(screen.getByRole('button', { name: 'Save search settings' }))
  expect(await screen.findByRole('alertdialog', { name: 'Re-embed the whole library?' })).toBeVisible()
  expect(await screen.findByText(/6 papers/)).toBeVisible()
  const estimated = calls.filter((call) => call.path === '/retrieval/reindex-estimate').map((call) => call.url.searchParams.get('profile'))
  expect(estimated).toEqual([small.key])
})
