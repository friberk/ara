// Test-after coverage (ARA-036 TDD audit): behaviour that shipped before any test covered it. Each test was
// confirmed by breaking the behaviour it covers, watching the test fail, and restoring the code.
import { screen, waitFor, within } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { json, mockApi, type Routes } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { SummaryCard } from '.'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const settings = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } }
const summary = (id: string, content: string, created_at: string, overrides: Record<string, unknown> = {}) => ({ id, paper_id: 'p1', document_id: 'd1', model: luna.key, reasoning_effort: 'low', content, citations: [], created_at, ...overrides })
const job = (id: string, state: string) => ({ id, kind: 'summary', state, stage: state, progress: state === 'completed' ? 100 : 10, attempts: 1, generation: 1, result: null, error_code: null, error_message: null, available_at: '2026-10-08T12:00:00Z', created_at: '2026-10-08T12:00:00Z', updated_at: '2026-10-08T12:00:00Z', error: null, paper_id: 'p1', paper_title: paper.title })
const never = () => new Promise<Response>(() => {})
afterEach(() => vi.unstubAllGlobals())

function mount(routes: Routes, value: Paper = paper) {
  mockApi(routes)
  return renderWithProviders(<TooltipProvider><GenerationSettingsProvider><SummaryCard paper={value} /></GenerationSettingsProvider></TooltipProvider>)
}

test('Given a summary that just finished, Then it opens in full', async () => {
  let done = false
  const { user } = mount({
    ...settings,
    'GET /papers/p1/summaries': () => json({ items: done ? [summary('s1', 'Fresh summary.', '2026-10-08T12:01:00Z')] : [] }),
    'POST /papers/p1/summaries': { job_id: 'j1', summary_id: null },
    'GET /jobs/j1': () => { done = true; return json(job('j1', 'completed')) },
  })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  const generate = await within(card).findByRole('button', { name: 'Generate summary' })
  await waitFor(() => expect(generate).toBeEnabled())
  await user.click(generate)
  expect(await within(card).findByRole('button', { name: 'Collapse summary' })).toHaveAttribute('aria-expanded', 'true')
})

test('Given a summary of an earlier PDF, Then the card marks it', async () => {
  mount({ ...settings, 'GET /papers/p1/summaries': { items: [summary('s1', 'Old text.', '2026-10-08T12:00:00Z', { document_id: 'd0' })] } })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByText('Earlier PDF')).toBeVisible()
})

test('Given summaries still loading, Then a loading placeholder is shown', async () => {
  mount({ ...settings, 'GET /papers/p1/summaries': never })
  expect(await screen.findByRole('status', { name: 'Loading summary' })).toBeInTheDocument()
})

test('Given summaries fail to load, Then the error is inline and Try again loads them', async () => {
  let failures = 0
  const { user } = mount({
    ...settings,
    'GET /papers/p1/summaries': () => (failures++ === 0 ? json({ code: 'UNAVAILABLE', message: 'Summaries could not load.' }, 503) : json({ items: [summary('s1', 'Loaded summary.', '2026-10-08T12:00:00Z')] })),
  })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByRole('alert')).toHaveTextContent('Summaries could not load.')
  await user.click(within(card).getByRole('button', { name: 'Try again' }))
  expect(await within(card).findByText('Loaded summary.')).toBeInTheDocument()
})

// Finish review: a paper without a usable PDF offers the next step (or waits) instead of a disabled action.
test('Given a PDF still processing, Then the card explains the wait and offers no action', async () => {
  mount(settings, { ...paper, document_status: 'processing' as const })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByText('The summary starts automatically when the PDF is ready.')).toBeVisible()
  expect(within(card).queryByRole('button', { name: /Generate summary|Attach PDF/ })).not.toBeInTheDocument()
})

test('Given a failed PDF, Then the card explains why and offers Attach PDF', async () => {
  mount(settings, { ...paper, document_status: 'failed' as const })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByText('PDF processing failed. Attach a text-based PDF to generate a summary.')).toBeVisible()
  expect(within(card).getByRole('button', { name: 'Attach PDF' })).toBeEnabled()
  expect(within(card).queryByRole('button', { name: 'Generate summary' })).not.toBeInTheDocument()
})

test('Given a model without structured output, Then Generate summary is disabled with the reason', async () => {
  mount({ ...settings, 'GET /models': { items: [{ ...luna, supports_structured_output: false }] } }, paper)
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByText('The selected model can’t write summaries. Choose another model in the composer.')).toBeVisible()
  expect(within(card).getByRole('button', { name: 'Generate summary' })).toBeDisabled()
})

test('Given no summary yet, Then Generate summary shows with no model or effort line', async () => {
  mount(settings)
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  // Waiting for enabled means the models have loaded, so a model line would already be rendered.
  await waitFor(() => expect(within(card).getByRole('button', { name: 'Generate summary' })).toBeEnabled())
  expect(within(card).queryByText(/Uses .* with/)).not.toBeInTheDocument()
})

test('Given a server that ignores the job filters, Then jobs of other papers and finished jobs show no progress here', async () => {
  mount({
    ...settings,
    'GET /jobs': { items: [{ ...job('j8', 'processing'), paper_id: 'another-paper' }, job('j9', 'completed'), { ...job('j10', 'processing'), kind: 'ingest' }] },
  })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByRole('button', { name: 'Generate summary' })).toBeVisible()
  expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument()
})

test('Given Generate summary pressed twice quickly, Then only one paid summary is requested', async () => {
  let posts = 0
  const { user } = mount({ ...settings, 'POST /papers/p1/summaries': () => { posts++; return never() } })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  const generate = await within(card).findByRole('button', { name: 'Generate summary' })
  await waitFor(() => expect(generate).toBeEnabled())
  await user.click(generate)
  await user.click(generate)
  expect(generate).toBeDisabled()
  expect(posts).toBe(1)
})
