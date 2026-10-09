// Automatic summaries (ARA-084): the card follows a summary the server starts when the PDF becomes ready.
import { screen, within } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { SummaryCard } from '.'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: [], year: 2024, abstract: null, doi: '10.1000/paper', sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const settings = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } }
const job = { id: 'auto', kind: 'summary', state: 'queued', stage: 'queued', progress: 0, attempts: 0, generation: 1, result: null, error_code: null, error_message: null, available_at: '2026-10-09T12:00:00Z', created_at: '2026-10-09T12:00:00Z', updated_at: '2026-10-09T12:00:00Z', error: null, paper_id: 'p1', paper_title: paper.title }
const budget = { code: 'DAILY_BUDGET_EXCEEDED', message: 'Today’s AI budget can’t cover this summary.', model: luna.key, reasoning_effort: 'low' }
afterEach(() => vi.unstubAllGlobals())

const card = (value: Paper) => <TooltipProvider><GenerationSettingsProvider><SummaryCard paper={value} /></GenerationSettingsProvider></TooltipProvider>

test('Given the PDF is still being retrieved, Then the card says the summary follows it and offers no upload', async () => {
  mockApi({ ...settings, 'GET /papers/p1/fulltext': { paper_id: 'p1', availability: 'open_copy_reported', locations: [], attempts: [], retrieval_job: { id: 'r1', kind: 'fulltext', state: 'processing', stage: 'fetching_pdf', progress: 40 } } })
  renderWithProviders(card({ ...paper, document_status: 'metadata_only', active_document_id: null }))
  const article = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(article).findByText('The summary starts when the PDF is ready.')).toBeVisible()
  expect(within(article).queryByRole('button', { name: /Attach PDF|Generate summary/ })).not.toBeInTheDocument()
})

test('Given the PDF becomes ready, When the server has queued its summary, Then the card follows it without a click', async () => {
  let ready = false
  const { calls } = mockApi({ ...settings, 'GET /jobs': () => json({ items: ready ? [job] : [] }), 'GET /jobs/auto': { ...job, state: 'processing', stage: 'summarizing', progress: 30 } })
  const view = renderWithProviders(card({ ...paper, document_status: 'processing' }))
  const article = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(article).findByText('The summary starts automatically when the PDF is ready.')).toBeVisible()
  ready = true
  view.rerender(card(paper))
  expect(await within(article).findByRole('progressbar', { name: 'Summary progress' })).toBeVisible()
  expect(await within(article).findByText('Summarizing sections')).toBeVisible()
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
})

test('Given the saved default cannot summarize, Then Generate summary is offered with the reason', async () => {
  mockApi({ ...settings, 'GET /papers/p1/summaries': { items: [], blocked: budget } })
  renderWithProviders(card(paper))
  const article = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(article).findByText('Not summarized automatically. Today’s AI budget can’t cover this summary.')).toBeVisible()
  expect(within(article).getByRole('button', { name: 'Generate summary' })).toBeVisible()
})

test('Given a processing PDF whose default cannot summarize, Then the card says the summary will not start by itself', async () => {
  mockApi({ ...settings, 'GET /papers/p1/summaries': { items: [], blocked: { ...budget, code: 'LOCAL_MODEL_NOT_READY', message: 'Download weights in Settings to use this model.' } } })
  renderWithProviders(card({ ...paper, document_status: 'processing' }))
  const article = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(article).findByText('The summary won’t start by itself. Download weights in Settings to use this model.')).toBeVisible()
  expect(within(article).queryByRole('button', { name: /Attach PDF|Generate summary/ })).not.toBeInTheDocument()
})
