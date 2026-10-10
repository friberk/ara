import { fireEvent, screen, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'

const history = [
  { id: 's1', provider: 'semantic_scholar', query: 'graph transformers', created_at: '2026-10-08T09:00:00Z', last_searched_at: '2026-10-08T11:00:00Z' },
  { id: 's2', provider: 'openalex', query: 'retrieval augmented generation', created_at: '2026-10-08T08:00:00Z', last_searched_at: '2026-10-08T10:00:00Z' },
]
afterEach(() => vi.unstubAllGlobals())

test('Given recent searches, Then the home page offers them beside example topics', async () => {
  mockApi({ 'GET /search-history': { items: history } })
  renderApp('/')
  const suggestions = await screen.findByRole('list', { name: 'Suggestions' })
  const recent = await within(suggestions).findByRole('link', { name: 'Recent search: graph transformers' })
  expect(recent).toHaveAttribute('href', '/search?q=graph+transformers&provider=semantic_scholar')
  expect(within(suggestions).getByRole('link', { name: 'Recent search: retrieval augmented generation' })).toBeVisible()
  expect(within(suggestions).getAllByRole('button', { name: /^Example topic:/ })).toHaveLength(1)
  expect(within(suggestions).getByRole('button', { name: 'Upload a PDF' })).toBeVisible()
})

test('Given search history is unavailable, Then example topics are offered instead', async () => {
  mockApi({ 'GET /search-history': () => json({ code: 'NOT_FOUND', message: 'Not found', request_id: 'r1' }, 404) })
  renderApp('/')
  const suggestions = await screen.findByRole('list', { name: 'Suggestions' })
  expect(within(suggestions).getAllByRole('button', { name: /^Example topic:/ })).toHaveLength(3)
  expect(within(suggestions).queryByRole('link', { name: /^Recent search:/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

const processing = { id: 'p1', title: null, authors: [], year: null, abstract: null, doi: null, sources: [], document_status: 'processing', active_document_id: 'd1', metadata_provenance: {} }
const ingest = { id: 'j1', kind: 'ingest', state: 'processing', stage: 'processing', progress: 20, attempts: 1, error: null, result: null, paper_id: 'p1' }
const pdf = () => new File(['%PDF-1.4 home'], 'sec18-han.pdf', { type: 'application/pdf' })

test('Given Upload a PDF on home, When a file is chosen, Then it uploads and the paper opens with its stages', async () => {
  mockApi({ 'POST /documents': () => json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }, 202), 'GET /papers/p1': processing, 'GET /jobs/j1': ingest })
  const { user } = renderApp('/')
  const suggestions = await screen.findByRole('list', { name: 'Suggestions' })
  const input = screen.getByLabelText('PDF file')
  const click = vi.spyOn(input, 'click')
  await user.click(within(suggestions).getByRole('button', { name: 'Upload a PDF' }))
  expect(click).toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await user.upload(input, pdf())
  const reader = await screen.findByRole('region', { name: 'PDF reader' }, { timeout: 4000 })
  const steps = await within(reader).findByRole('list', { name: 'Preparation steps' })
  expect(within(steps).getByText('Uploaded')).toBeVisible()
  expect(within(steps).getByText('Reading pages').closest('li')).toHaveAttribute('aria-current', 'step')
  expect(screen.queryByText(/in the background/i)).not.toBeInTheDocument()
})

test('Given a PDF dropped on home that is already in the library, Then that paper opens with a note', async () => {
  mockApi({ 'POST /documents': () => json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: true }, 202), 'GET /papers/p1': { ...processing, title: 'A Bad Dream', document_status: 'ready' }, 'GET /jobs/j1': { ...ingest, state: 'completed', stage: 'completed' } })
  renderApp('/')
  await screen.findByRole('list', { name: 'Suggestions' })
  fireEvent.drop(screen.getByRole('main'), { dataTransfer: { files: [pdf()], types: ['Files'] } })
  expect(await screen.findByRole('heading', { level: 1, name: 'A Bad Dream' }, { timeout: 4000 })).toBeVisible()
  expect(await screen.findByText('This PDF is already in your library, so its paper opened.')).toBeVisible()
})

test('Given an upload from home fails, Then the reason stays under the composer with a way to retry', async () => {
  mockApi({ 'POST /documents': () => json({ code: 'INVALID_PDF_SIGNATURE', message: 'Upload a valid PDF file.' }, 415) })
  const { user } = renderApp('/')
  await screen.findByRole('list', { name: 'Suggestions' })
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  expect(await screen.findByRole('alert')).toHaveTextContent('Upload a valid PDF file.')
  expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible()
})
