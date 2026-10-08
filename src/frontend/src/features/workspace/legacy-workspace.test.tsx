// Legacy behaviour tests moved from pages/workflows.test.tsx (ARA-033). The feature owner replaces them
// with tests for the redesigned UI while keeping the same behavioural coverage.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'

const paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'metadata_only', active_document_id: null, metadata_provenance: {} }
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function mount(path: string) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>); return client }
afterEach(() => vi.unstubAllGlobals())


test('Given metadata only, Then analysis stays disabled and PDF upload is offered', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/papers/p1') ? response(paper) : response({ items: [] })))
  mount('/papers/p1')
  expect(await screen.findByRole('heading', { name: paper.title })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Generate summary' })).toBeDisabled()
  expect(screen.getByLabelText('PDF file')).toBeVisible()
  expect(screen.getByText(/Upload a PDF to enable/)).toBeVisible()
})


test('Given field provenance, Then readers can see the source of bibliographic metadata', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/papers/p1') ? response({ ...paper, metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } } }) : response({ items: [] })))
  mount('/papers/p1')
  await screen.findByRole('heading', { name: paper.title })
  await userEvent.setup().click(screen.getByText('Metadata sources'))
  expect(screen.getByText('Title: edited by you')).toBeVisible()
  expect(screen.getByText('Authors: OpenAlex')).toBeVisible()
})


test('Given provider metadata, When only the title is edited, Then other fields keep their provider provenance', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/papers/p1') && init?.method === 'PATCH') { const payload: unknown = JSON.parse(String(init.body)); if (typeof payload !== 'object' || payload === null || Object.keys(payload).join(',') !== 'title') return response({ code: 'unexpected_correction', message: 'Only changed fields should be corrected.' }, 422); return response({ ...paper, title: 'Corrected title', metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } } }) }
    if (url.endsWith('/papers/p1')) return response(paper)
    return response({ items: [] })
  }))
  mount('/papers/p1'); const user = userEvent.setup(); await screen.findByRole('heading', { name: paper.title }); await user.click(screen.getByRole('button', { name: 'Edit' })); const title = screen.getByRole('textbox', { name: 'Title' }); await user.clear(title); await user.type(title, 'Corrected title'); await user.click(screen.getByRole('button', { name: 'Save bibliography' }))
  expect(await screen.findByRole('heading', { name: 'Corrected title' })).toBeVisible()
  await user.click(screen.getByText('Metadata sources')); expect(screen.getByText('Authors: OpenAlex')).toBeVisible()
})

