// Test-after coverage (ARA-038): these behaviours shipped before their tests. Each test was checked
// against a deliberate mutation of the implementation to confirm it can fail.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import { json, mockApi } from '@/test/fetch-routes'
import { testClient } from '@/test/render'

const hit = { provider: 'openalex', external_id: 'W1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, external_url: null, pdf_url: null, saved_paper_id: null }
const page = (items: unknown[], extra: object = {}) => ({ provider: 'openalex', items, next_cursor: null, total: items.length, ...extra })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function LocationProbe() { const location = useLocation(); return <output aria-label="Location">{`${location.pathname}${location.search}`}</output> }
function mount(path: string) {
  const user = userEvent.setup()
  render(<QueryClientProvider client={testClient()}><MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter></QueryClientProvider>)
  return { user }
}
function deferred() {
  let resolve: (response: Response) => void = () => {}
  const promise = new Promise<Response>((done) => { resolve = done })
  return { promise, resolve }
}
const statusWith = (text: string) => screen.getAllByRole('status').find((element) => element.textContent?.includes(text))

test('Given a search in flight, Then skeleton rows are announced as searching the provider', async () => {
  mockApi({ 'GET /search': () => new Promise<Response>(() => {}) })
  mount('/search?q=graphs&provider=semantic_scholar')
  await waitFor(() => expect(statusWith('Searching Semantic Scholar…')).toBeDefined())
  const status = statusWith('Searching Semantic Scholar…') as HTMLElement
  expect(status.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThanOrEqual(3)
  expect(screen.queryByRole('article')).not.toBeInTheDocument()
})

test('Given Load more is pressed, Then it stays disabled and busy until the next page arrives', async () => {
  const next = deferred()
  mockApi({ 'GET /search': ({ url }) => (url.searchParams.get('cursor') === 'c2' ? next.promise : json(page([hit], { next_cursor: 'c2', total: 2 }))) })
  const { user } = mount('/search?q=evidence&provider=openalex')
  const more = await screen.findByRole('button', { name: 'Load more' })
  expect(more).toBeEnabled()
  await user.click(more)
  await waitFor(() => expect(more).toBeDisabled())
  expect(more).toHaveAttribute('aria-busy', 'true')
  next.resolve(json(page([{ ...hit, external_id: 'W2', title: 'Second page paper' }], { next_cursor: null, total: 2 })))
  expect(await screen.findByRole('article', { name: 'Second page paper' })).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

test('Given a result already in the library, When Ask about this paper is chosen, Then its workspace opens without saving again', async () => {
  const { calls } = mockApi({ 'GET /search': page([{ ...hit, saved_paper_id: 'p9' }]) })
  const { user } = mount('/search?q=evidence&provider=openalex')
  const row = await screen.findByRole('article', { name: hit.title })
  await user.click(within(row).getByRole('button', { name: 'Ask about this paper' }))
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/papers\/p9$/))
  expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0)
})

test('Given /search without a query, Then an intro and a focused empty composer appear and nothing is searched', async () => {
  const { calls } = mockApi({})
  mount('/search')
  expect(await screen.findByRole('heading', { level: 1, name: 'Search the literature' })).toBeVisible()
  const composer = screen.getByRole('textbox', { name: 'Research topic' })
  expect(composer).toHaveValue('')
  expect(composer).toHaveFocus()
  expect(composer).toHaveAttribute('placeholder', 'Search papers by topic, title or research question')
  expect(screen.getByRole('button', { name: 'Search papers' })).toBeDisabled()
  expect(calls.some((call) => call.path === '/search')).toBe(false)
})

test('Given provider text with hidden characters, Then titles and authors render clean', async () => {
  mockApi({ 'GET /search': page([{ ...hit, title: 'Exploiting input\u0007 sanitization', authors: ['Efe Barlas', 'Xin Du'] }]) })
  mount('/search?q=regex&provider=openalex')
  const row = await screen.findByRole('article', { name: 'Exploiting input sanitization' })
  expect(within(row).getByText('Efe Barlas, Xin Du')).toBeVisible()
})

describe('abstract clamping', () => {
  const observer = window.ResizeObserver
  afterEach(() => { window.ResizeObserver = observer })
  const abstract = 'A long abstract that runs well past three lines when rendered in the result column of the search thread.'
  // jsdom has no layout: report the clamped paragraph as taller than its box, and observe it at once.
  function measure(scroll: number, client: number) {
    vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockImplementation(function (this: Element) { return this.classList.contains('line-clamp-3') ? scroll : 0 })
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockImplementation(function (this: Element) { return this.classList.contains('line-clamp-3') ? client : 0 })
    // setup.ts installs a non-configurable observer, so swap the value and restore it after the test.
    window.ResizeObserver = class {
      private readonly callback: ResizeObserverCallback
      constructor(callback: ResizeObserverCallback) { this.callback = callback }
      observe(target: Element) { this.callback([{ target, contentRect: target.getBoundingClientRect(), borderBoxSize: [], contentBoxSize: [], devicePixelContentBoxSize: [] }], this as unknown as ResizeObserver) }
      unobserve() {}
      disconnect() {}
    }
  }

  test('Given an abstract taller than three lines, When Show more and Show less are pressed, Then it expands and clamps again', async () => {
    measure(120, 72)
    mockApi({ 'GET /search': page([{ ...hit, abstract }]) })
    const { user } = mount('/search?q=evidence&provider=openalex')
    const row = await screen.findByRole('article', { name: hit.title })
    const toggle = await within(row).findByRole('button', { name: 'Show more' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(toggle.getAttribute('aria-controls') ?? '')).toHaveTextContent(abstract)
    await user.click(toggle)
    expect(within(row).getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true')
    await user.click(within(row).getByRole('button', { name: 'Show less' }))
    expect(within(row).getByRole('button', { name: 'Show more' })).toHaveAttribute('aria-expanded', 'false')
  })

  test('Given an abstract that fits in three lines, Then no toggle is offered', async () => {
    measure(72, 72)
    mockApi({ 'GET /search': page([{ ...hit, abstract }]) })
    mount('/search?q=evidence&provider=openalex')
    const row = await screen.findByRole('article', { name: hit.title })
    expect(within(row).getByText(abstract)).toBeVisible()
    expect(within(row).queryByRole('button', { name: /Show (more|less)/ })).not.toBeInTheDocument()
  })
})
