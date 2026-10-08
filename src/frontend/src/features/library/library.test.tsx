import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import { mockApi } from '@/test/fetch-routes'
import { testClient } from '@/test/render'

const ready = { id: 'p1', title: 'Attention is all you need', authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit'], year: 2017, abstract: 'The dominant sequence transduction models are based on recurrent networks.', doi: '10.48550/arXiv.1706.03762', sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const saved = { ...ready, id: 'p2', title: 'Exploiting input sanitization', authors: ['Efe Barlas'], year: 2022, abstract: null, document_status: 'metadata_only', active_document_id: null }
afterEach(() => vi.unstubAllGlobals())

function LocationProbe() { const location = useLocation(); return <output aria-label="Location">{`${location.pathname}${location.search}${location.hash}`}</output> }
function mount(path: string) {
  const user = userEvent.setup()
  render(<QueryClientProvider client={testClient()}><MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter></QueryClientProvider>)
  return { user }
}

test('Given saved papers, Then each row links to its workspace with authors, year and document status', async () => {
  mockApi({ 'GET /papers': { items: [ready, saved] } })
  mount('/library')
  expect(await screen.findByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  const main = screen.getByRole('main')
  const row = (await within(main).findByRole('link', { name: ready.title })).closest('article') as HTMLElement
  expect(within(row).getByRole('link', { name: ready.title })).toHaveAttribute('href', '/papers/p1')
  expect(within(row).getByText('Ashish Vaswani, Noam Shazeer, Niki Parmar et al.')).toBeVisible()
  expect(within(row).getByText('2017')).toBeVisible()
  expect(within(row).getByText('Ready to read')).toBeVisible()
  expect(within(main).getByText('2 papers')).toBeVisible()
  expect(within(main).getByText('PDF needed')).toBeVisible()
})

test('Given a PDF upload accepted, Then durable processing status and the new paper are offered', async () => {
  mockApi({
    'POST /documents': { paper_id: 'p1', document_id: 'd1', job_id: 'j1' },
    'GET /jobs/j1': { id: 'j1', kind: 'ingest', state: 'processing', stage: 'extracting', progress: 40, attempts: 1, error: null, result: null },
  })
  const { user } = mount('/library')
  await user.click(await screen.findByRole('button', { name: 'Upload PDF' }))
  await user.upload(await screen.findByLabelText('PDF file'), new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Upload PDF' }))
  expect(await screen.findByText(/extracting/)).toBeVisible()
  await waitFor(() => expect(screen.getByRole('link', { name: 'Open uploaded paper' })).toHaveAttribute('href', '/papers/p1'))
})

test('Given an oversized PDF, Then upload stays disabled with a recoverable explanation', async () => {
  mockApi({})
  const { user } = mount('/library#upload')
  const file = new File(['%PDF'], 'large.pdf', { type: 'application/pdf' })
  Object.defineProperty(file, 'size', { value: 26 * 1024 * 1024 })
  await user.upload(await screen.findByLabelText('PDF file'), file)
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByRole('alert')).toHaveTextContent('exceeds 25 MB')
  expect(within(dialog).getByRole('button', { name: 'Upload PDF' })).toBeDisabled()
})

test('Given the #upload link, Then the upload dialog opens and closing it clears the hash', async () => {
  mockApi({})
  const { user } = mount('/library#upload')
  expect(await screen.findByRole('dialog', { name: 'Upload a paper' })).toBeVisible()
  expect(screen.getByLabelText('PDF file')).toBeInTheDocument()
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/library$/)
})

test('Given the library filter, When typing, Then the URL and the request follow the text', async () => {
  const { calls } = mockApi({ 'GET /papers': ({ url }) => new Response(JSON.stringify({ items: url.searchParams.get('q') === 'attention' ? [ready] : [ready, saved] }), { headers: { 'Content-Type': 'application/json' } }) })
  const { user } = mount('/library?q=atten')
  const filter = await screen.findByRole('searchbox', { name: 'Filter library' })
  expect(filter).toHaveValue('atten')
  await waitFor(() => expect(calls.some((call) => call.path === '/papers' && call.url.searchParams.get('q') === 'atten')).toBe(true))
  await user.type(filter, 'tion')
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent('/library?q=attention'))
  await waitFor(() => expect(calls.some((call) => call.path === '/papers' && call.url.searchParams.get('q') === 'attention')).toBe(true))
  expect(calls.some((call) => call.path === '/papers' && call.url.searchParams.get('q') === 'attent')).toBe(false)
})

test('Given a filter with no matches, Then the filter can be cleared', async () => {
  mockApi({ 'GET /papers': ({ url }) => new Response(JSON.stringify({ items: url.searchParams.get('q') ? [] : [ready] }), { headers: { 'Content-Type': 'application/json' } }) })
  const { user } = mount('/library?q=quantum')
  expect(await screen.findByRole('heading', { name: 'No papers match “quantum”' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Clear filter' }))
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/library$/))
  expect(await within(screen.getByRole('main')).findByRole('link', { name: ready.title })).toBeVisible()
})

test('Given an empty library, Then searching and uploading are offered', async () => {
  mockApi({})
  const { user } = mount('/library')
  expect(await screen.findByRole('heading', { name: 'Your library is empty' })).toBeVisible()
  expect(within(screen.getByRole('main')).getByRole('link', { name: 'Search papers' })).toHaveAttribute('href', '/')
  await user.click(screen.getByRole('button', { name: 'Upload a PDF' }))
  expect(await screen.findByRole('dialog', { name: 'Upload a paper' })).toBeVisible()
})
