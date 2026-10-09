import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const ingest = { kind: 'ingest', state: 'processing', stage: 'processing', progress: 20, attempts: 1, error: null, result: null }
const pdf = (name: string) => new File([`%PDF-1.4 ${name}`], name, { type: 'application/pdf' })

test('Given several PDFs dropped on the library, Then each becomes its own paper with its own progress row', async () => {
  let next = 0
  const { calls } = mockApi({
    'POST /documents': () => { next += 1; return new Response(JSON.stringify(next === 3 ? { paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: true } : { paper_id: `new-${next}`, document_id: `d-${next}`, job_id: `j-${next}`, duplicate: false }), { status: 202, headers: { 'Content-Type': 'application/json' } }) },
    'GET /jobs/j-1': { ...ingest, id: 'j-1' },
    'GET /jobs/j-2': { ...ingest, id: 'j-2', state: 'completed', stage: 'completed', progress: 100 },
    'GET /jobs/j1': { ...ingest, id: 'j1', state: 'completed', stage: 'completed', progress: 100 },
  })
  mount('/library')
  const main = await screen.findByRole('main')
  await screen.findByRole('heading', { name: 'Your library is empty' })
  // Drops land anywhere on the page, like a file manager.
  fireEvent.drop(main, { dataTransfer: { files: [pdf('first.pdf'), pdf('second.pdf'), pdf('again.pdf')], types: ['Files'] } })
  const uploads = await screen.findByRole('list', { name: 'Uploads' })
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST' && call.path === '/documents')).toHaveLength(3))
  const row = (name: string) => within(uploads).getByText(name).closest('li') as HTMLElement
  await waitFor(() => expect(within(row('first.pdf')).getByText('Reading pages')).toBeVisible())
  await waitFor(() => expect(within(row('second.pdf')).getByText('Ready')).toBeVisible())
  expect(within(row('second.pdf')).getByRole('link', { name: 'Open second.pdf' })).toHaveAttribute('href', '/papers/new-2')
  expect(within(row('again.pdf')).getByText('Already in your library')).toBeVisible()
  expect(within(row('again.pdf')).getByRole('link', { name: 'Open again.pdf' })).toHaveAttribute('href', '/papers/p1')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('Given the Upload PDF button, Then it opens a picker for several PDFs without a dialog', async () => {
  const { calls } = mockApi({ 'POST /documents': () => new Response(JSON.stringify({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }), { status: 202 }), 'GET /jobs/j1': { ...ingest, id: 'j1' } })
  const { user } = mount('/library')
  await screen.findByRole('heading', { level: 1, name: 'Library' })
  const input = screen.getByLabelText('PDF files')
  expect(input).toHaveAttribute('multiple')
  const click = vi.spyOn(input, 'click')
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  expect(click).toHaveBeenCalled()
  await user.upload(input, [pdf('one.pdf'), pdf('two.pdf')])
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(2))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('Given an oversized PDF among others, Then only that row explains the limit and the rest upload', async () => {
  const { calls } = mockApi({ 'POST /documents': () => new Response(JSON.stringify({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }), { status: 202 }), 'GET /jobs/j1': { ...ingest, id: 'j1' } })
  const { user } = mount('/library')
  await screen.findByRole('heading', { level: 1, name: 'Library' })
  const large = pdf('large.pdf')
  Object.defineProperty(large, 'size', { value: 26 * 1024 * 1024 })
  await user.upload(screen.getByLabelText('PDF files'), [large, pdf('fine.pdf')])
  const uploads = await screen.findByRole('list', { name: 'Uploads' })
  expect(within(within(uploads).getByText('large.pdf').closest('li') as HTMLElement).getByText('This PDF exceeds 25 MB. Choose a smaller file.')).toBeVisible()
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1))
})

test('Given the #upload link, Then an inline drop area opens and closing it clears the hash', async () => {
  mockApi({})
  const { user } = mount('/library#upload')
  const area = await screen.findByRole('region', { name: 'Add PDFs' })
  expect(within(area).getByRole('button', { name: 'Choose PDFs' })).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await user.click(within(area).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Add PDFs' })).not.toBeInTheDocument())
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
  const input = screen.getByLabelText('PDF files')
  const click = vi.spyOn(input, 'click')
  await user.click(screen.getByRole('button', { name: 'Upload a PDF' }))
  expect(click).toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('Given an upload still being read, Then its row is named by its file until a title is known', async () => {
  mockApi({ 'GET /papers': { items: [{ ...saved, id: 'p3', title: null, authors: [], year: null, document_status: 'processing', active_document_id: 'd3', file_name: 'sec18-han.pdf' }] } })
  mount('/library')
  expect(await within(screen.getByRole('main')).findByRole('link', { name: 'sec18-han.pdf' })).toHaveAttribute('href', '/papers/p3')
})

test('Given an uploaded PDF that is readable while its details are looked up, Then its row says Ready and notes the lookup', async () => {
  mockApi({
    'POST /documents': () => new Response(JSON.stringify({ paper_id: 'p5', document_id: 'd5', job_id: 'j5', duplicate: false }), { status: 202 }),
    'GET /jobs/j5': { ...ingest, id: 'j5', state: 'completed', stage: 'completed', progress: 100 },
    'GET /jobs': ({ url }) => new Response(JSON.stringify({ items: url.searchParams.get('kind') === 'metadata' ? [{ ...ingest, id: 'm5', kind: 'metadata', state: 'queued', stage: 'retry_wait', paper_id: 'p5' }] : [] })),
  })
  const { user } = mount('/library')
  await screen.findByRole('heading', { level: 1, name: 'Library' })
  await user.upload(screen.getByLabelText('PDF files'), pdf('slow-details.pdf'))
  const row = (await within(await screen.findByRole('list', { name: 'Uploads' })).findByText('slow-details.pdf')).closest('li') as HTMLElement
  await waitFor(() => expect(within(row).getByText('Ready')).toBeVisible())
  expect(within(row).getByText('Finding paper details')).toBeVisible()
})
