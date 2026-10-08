import { screen, waitFor, within } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { SummaryCard } from '.'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const summary = (id: string, content: string, created_at: string, model = luna.key) => ({ id, paper_id: 'p1', document_id: 'd1', model, reasoning_effort: 'low', content, citations: [], created_at })
const job = (id: string, state: string, stage: string, progress: number) => ({ id, kind: 'summary', state, stage, progress, attempts: 1, generation: 1, result: null, error_code: null, error_message: null, available_at: '2026-10-08T12:00:00Z', created_at: '2026-10-08T12:00:00Z', updated_at: '2026-10-08T12:00:00Z', error: null, paper_id: 'p1', paper_title: paper.title })
const settings = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } }
afterEach(() => vi.unstubAllGlobals())

function mount(value: Paper = paper) {
  return renderWithProviders(<TooltipProvider><GenerationSettingsProvider><SummaryCard paper={value} /></GenerationSettingsProvider></TooltipProvider>)
}

test('Given no summary, When Generate summary is pressed, Then staged progress is shown and the stored summary follows', async () => {
  let jobPolls = 0
  let done = false
  const { calls } = mockApi({
    ...settings,
    'GET /papers/p1/summaries': () => json({ items: done ? [summary('s1', 'The study evaluates the Orion-12 dataset.', '2026-10-08T12:01:00Z')] : [] }),
    'POST /papers/p1/summaries': { job_id: 'j1', summary_id: null },
    'GET /jobs/j1': () => {
      jobPolls++
      if (jobPolls === 1) return json(job('j1', 'processing', 'summarizing', 40))
      done = true
      return json(job('j1', 'completed', 'completed', 100))
    },
  })
  const { user } = mount()
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  const generate = await within(card).findByRole('button', { name: 'Generate summary' })
  await waitFor(() => expect(generate).toBeEnabled())
  await user.click(generate)
  expect(await within(card).findByRole('progressbar', { name: 'Summary progress' })).toBeVisible()
  expect(within(card).getByText('Summarizing sections')).toBeVisible()
  expect(await within(card).findByText('The study evaluates the Orion-12 dataset.', undefined, { timeout: 4000 })).toBeVisible()
  expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument()
  expect(within(card).getByText('Luna')).toBeVisible()
  expect(within(card).getByText('Low reasoning')).toBeVisible()
  const post = calls.find((call) => call.method === 'POST')
  expect(post?.body).toMatchObject({ model: luna.key, reasoning_effort: 'low' })
  expect((post?.body as { request_id: string }).request_id).toMatch(/^[0-9a-f-]{36}$/)
})

test('Given a summary job already running, When the card mounts after a reload, Then it reattaches to the job progress', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /jobs': ({ url }) => json({ items: url.searchParams.get('paper_id') === 'p1' && url.searchParams.get('kind') === 'summary' && url.searchParams.get('active') === 'true' ? [job('j2', 'processing', 'combining', 80)] : [] }),
    'GET /jobs/j2': job('j2', 'processing', 'combining', 80),
  })
  mount()
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByRole('progressbar', { name: 'Summary progress' })).toBeVisible()
  expect(await within(card).findByText('Combining the summary')).toBeVisible()
  expect(within(card).queryByRole('button', { name: 'Generate summary' })).not.toBeInTheDocument()
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
})

test('Given two summary versions, Then the latest shows first and an earlier version can be chosen', async () => {
  mockApi({
    ...settings,
    'GET /papers/p1/summaries': { items: [summary('s2', 'Second version text.', '2026-10-08T13:00:00Z'), summary('s1', 'First version text.', '2026-10-08T12:00:00Z', 'gpt-5.6-unlisted')] },
  })
  const { user } = mount()
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByText('Second version text.')).toBeInTheDocument()
  await user.click(within(card).getByRole('button', { name: 'Version 2 of 2' }))
  await user.click(await screen.findByRole('menuitemradio', { name: /Version 1/ }))
  expect(await within(card).findByText('First version text.')).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: 'Version 1 of 2' })).toBeVisible()
  // A model the server no longer lists keeps its exact stored ID.
  expect(within(card).getByText('gpt-5.6-unlisted')).toBeVisible()
})

test('Given a long summary, When expanded and collapsed, Then the full text toggles behind one control', async () => {
  mockApi({ ...settings, 'GET /papers/p1/summaries': { items: [summary('s1', 'Complete summary text.', '2026-10-08T12:00:00Z')] } })
  const { user } = mount()
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  const toggle = await within(card).findByRole('button', { name: 'Show full summary' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await user.click(toggle)
  expect(within(card).getByRole('button', { name: 'Collapse summary' })).toHaveAttribute('aria-expanded', 'true')
})

test('Given a metadata-only paper, Then summary generation explains that a PDF is needed', async () => {
  mockApi(settings)
  mount({ ...paper, document_status: 'metadata_only', active_document_id: null })
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  expect(await within(card).findByRole('button', { name: 'Generate summary' })).toBeDisabled()
  expect(within(card).getByText('Attach a PDF to generate a summary.')).toBeVisible()
})
