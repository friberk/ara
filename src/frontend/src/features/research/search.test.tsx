import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import { json, mockApi } from '@/test/fetch-routes'
import { testClient } from '@/test/render'

const paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'metadata_only', active_document_id: null, metadata_provenance: {} }
const hit = { provider: 'openalex', external_id: 'W1', title: paper.title, authors: ['A. Author'], year: 2024, abstract: null, doi: null, external_url: null, pdf_url: null, saved_paper_id: null }
const rich = {
  ...hit,
  external_id: 'W2',
  title: 'Graph transformers for molecules',
  authors: ['Ada Lovelace', 'Alan Turing', 'Grace Hopper', 'Edsger Dijkstra'],
  year: 2023,
  abstract: 'We study attention over molecular graphs.',
  doi: '10.1234/graphs.2023',
  external_url: 'https://www.semanticscholar.org/paper/abc',
  pdf_url: 'https://example.org/graphs.pdf',
}
afterEach(() => vi.unstubAllGlobals())

function LocationProbe() { const location = useLocation(); return <output aria-label="Location">{`${location.pathname}${location.search}${location.hash}`}</output> }
function mount(path: string) {
  const user = userEvent.setup()
  render(<QueryClientProvider client={testClient()}><MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter></QueryClientProvider>)
  return { user }
}
const page = (items: unknown[], extra: object = {}) => ({ provider: 'openalex', items, next_cursor: null, total: items.length, ...extra })

test('Given search results, When one is saved, Then it is confirmed and can be opened from the row', async () => {
  const { calls } = mockApi({ 'GET /search': page([hit], { next_cursor: 'page2', total: 40 }), 'POST /papers': paper })
  const { user } = mount('/search')
  await user.type(await screen.findByRole('textbox', { name: 'Research topic' }), 'retrieval')
  await user.click(screen.getByRole('button', { name: 'Search papers' }))
  const row = await screen.findByRole('article', { name: paper.title })
  expect(within(row).getByRole('heading', { level: 2, name: paper.title })).toBeVisible()
  await user.click(within(row).getByRole('button', { name: 'Save to library' }))
  expect(await screen.findByText('Saved to library')).toBeVisible()
  expect(await within(row).findByRole('link', { name: 'Open paper' })).toHaveAttribute('href', '/papers/p1')
  expect(within(row).getByText('In library')).toBeVisible()
  expect(within(row).queryByRole('button', { name: 'Save to library' })).not.toBeInTheDocument()
  expect(calls.find((call) => call.method === 'POST' && call.path === '/papers')?.body).toEqual({ provider: 'openalex', external_id: 'W1' })
  expect(screen.getByRole('button', { name: 'Load more' })).toBeVisible()
})

test('Given a save, Then the row shows In library without querying the provider again', async () => {
  // Saving marks matching hits in the cache; re-querying OpenAlex or Semantic Scholar would risk rate limits.
  const { calls } = mockApi({ 'GET /search': page([hit]), 'POST /papers': paper })
  const { user } = mount('/search?q=evidence&provider=openalex')
  const row = await screen.findByRole('article', { name: paper.title })
  await user.click(within(row).getByRole('button', { name: 'Save to library' }))
  expect(await within(row).findByRole('link', { name: 'Open paper' })).toHaveAttribute('href', '/papers/p1')
  expect(within(row).getByText('In library')).toBeVisible()
  await act(() => new Promise((resolve) => setTimeout(resolve, 50)))
  expect(calls.filter((call) => call.path === '/search')).toHaveLength(1)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('Given a result, Then title, authors, year, abstract and links are shown', async () => {
  mockApi({ 'GET /search': page([rich], { total: 1234 }) })
  mount('/search?q=graph+transformers&provider=openalex')
  expect(await screen.findByRole('heading', { level: 1, name: 'graph transformers' })).toBeVisible()
  expect(await screen.findByText('1,234 results from OpenAlex')).toBeVisible()
  const row = await screen.findByRole('article', { name: rich.title })
  expect(within(row).getByText('Ada Lovelace, Alan Turing, Grace Hopper et al.')).toHaveAttribute('title', rich.authors.join(', '))
  expect(within(row).getByText('2023')).toBeVisible()
  expect(within(row).getByText(rich.abstract)).toBeVisible()
  expect(within(row).getByRole('link', { name: /10\.1234\/graphs\.2023/ })).toHaveAttribute('href', 'https://doi.org/10.1234/graphs.2023')
  expect(within(row).getByRole('link', { name: /Semantic Scholar/ })).toHaveAttribute('href', rich.external_url)
  expect(within(row).getByRole('link', { name: /PDF/ })).toHaveAttribute('href', rich.pdf_url)
})

test('Given a result already in the library, Then it shows In library with Open paper and no save action', async () => {
  mockApi({ 'GET /search': page([{ ...rich, saved_paper_id: 'p9' }]) })
  mount('/search?q=graphs&provider=openalex')
  const row = await screen.findByRole('article', { name: rich.title })
  expect(within(row).getByText('In library')).toBeVisible()
  expect(within(row).getByRole('link', { name: 'Open paper' })).toHaveAttribute('href', '/papers/p9')
  expect(within(row).getByRole('link', { name: rich.title })).toHaveAttribute('href', '/papers/p9')
  expect(within(row).queryByRole('button', { name: 'Save to library' })).not.toBeInTheDocument()
})

test('Given an unsaved result, When Ask about this paper is chosen, Then it is saved and its workspace opens', async () => {
  const { calls } = mockApi({ 'GET /search': page([hit]), 'POST /papers': paper, 'GET /papers/p1': paper })
  const { user } = mount('/search?q=evidence&provider=openalex')
  const row = await screen.findByRole('article', { name: paper.title })
  await user.click(within(row).getByRole('button', { name: 'Ask about this paper' }))
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent('/papers/p1'))
  expect(calls.filter((call) => call.method === 'POST' && call.path === '/papers')).toHaveLength(1)
})

test('Given a provider limit, When searching, Then the busy provider and a retry are shown inline', async () => {
  mockApi({ 'GET /search': () => json({ code: 'PROVIDER_RATE_LIMITED', message: 'The academic provider is rate limited. Try again shortly.', request_id: 'r1' }, 429) })
  const { user } = mount('/search')
  await user.type(await screen.findByRole('textbox', { name: 'Research topic' }), 'graphs')
  await user.click(screen.getByRole('button', { name: 'Search papers' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('OpenAlex is busy')
  expect(within(alert).getByRole('button', { name: 'Try again' })).toBeVisible()
})

test('Given no results, Then a broader topic or the other provider is suggested', async () => {
  const { calls } = mockApi({ 'GET /search': page([]), 'POST /search-history': { id: 's2', provider: 'semantic_scholar', query: 'zzz', created_at: '', last_searched_at: '' } })
  const { user } = mount('/search?q=zzz&provider=openalex')
  expect(await screen.findByRole('heading', { name: 'No papers found' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Search Semantic Scholar instead' }))
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent('/search?q=zzz&provider=semantic_scholar'))
  await waitFor(() => expect(calls.some((call) => call.path === '/search' && call.url.searchParams.get('provider') === 'semantic_scholar')).toBe(true))
})

test('Given a search thread, When the docked composer refines it, Then the search is recorded and the new results open', async () => {
  const { calls } = mockApi({ 'GET /search': page([rich]), 'POST /search-history': { id: 's1', provider: 'openalex', query: 'graph neural networks', created_at: '', last_searched_at: '' } })
  const { user } = mount('/search?q=graphs&provider=openalex')
  await screen.findByRole('article', { name: rich.title })
  const composer = screen.getByRole('textbox', { name: 'Research topic' })
  expect(composer).toHaveValue('graphs')
  await user.clear(composer)
  await user.type(composer, 'graph neural networks{Enter}')
  await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/search-history')?.body).toEqual({ provider: 'openalex', query: 'graph neural networks' }))
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent('/search?q=graph+neural+networks&provider=openalex'))
  expect(await screen.findByRole('heading', { level: 1, name: 'graph neural networks' })).toBeVisible()
  // A deep link alone never records history; only the explicit submission did.
  expect(calls.filter((call) => call.method === 'POST' && call.path === '/search-history')).toHaveLength(1)
})
