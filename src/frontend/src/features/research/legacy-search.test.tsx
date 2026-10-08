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


test('Given search results, When saved, Then the paper can be opened in the library', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/search?')) return response({ provider: 'openalex', items: [{ provider: 'openalex', external_id: 'W1', title: paper.title, authors: paper.authors, year: 2024, abstract: null, doi: null, external_url: null, pdf_url: null }], next_cursor: 'page2', total: 1 })
    if (url.endsWith('/papers') && init?.method === 'POST') return response(paper)
    return response({ items: [] })
  }))
  mount('/search')
  const user = userEvent.setup()
  await user.type(await screen.findByRole('textbox', { name: 'Research topic' }), 'retrieval')
  await user.click(screen.getByRole('button', { name: 'Search papers' }))
  expect(await screen.findByRole('heading', { name: paper.title })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Save to library' }))
  expect(await screen.findByRole('link', { name: 'Open paper' })).toHaveAttribute('href', '/papers/p1')
  expect(screen.getByRole('button', { name: 'Load more' })).toBeVisible()
})


test('Given a provider limit, When searching, Then recovery is shown', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ code: 'rate_limited', message: 'Provider is busy. Try again later.', request_id: 'r1' }, 429)))
  mount('/search'); const user = userEvent.setup()
  await user.type(await screen.findByRole('textbox', { name: 'Research topic' }), 'graphs')
  await user.click(screen.getByRole('button', { name: 'Search papers' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Provider is busy')
})

