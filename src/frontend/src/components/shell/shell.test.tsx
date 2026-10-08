import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { renderApp, renderWithProviders } from '@/test/render'
import { json, mockApi, noContent } from '@/test/fetch-routes'
import { ShellHeader } from './shell-header'
import { HeaderSlotContext } from './shell-header-context'

const paper = (id: string, title: string) => ({ id, title, authors: ['Ada Researcher'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: `d-${id}`, metadata_provenance: {} })
const search = { id: 's1', provider: 'semantic_scholar', query: 'regular expressions', created_at: '2026-10-08T09:00:00Z', last_searched_at: '2026-10-08T11:00:00Z' }
afterEach(() => vi.unstubAllGlobals())

test('Given library papers, Then the sidebar lists recent papers linking to their workspaces', async () => {
  mockApi({ 'GET /papers': { items: [paper('p1', 'Attention Is All You Need'), paper('p2', 'Exploiting input sanitization')] } })
  renderApp('/')
  const link = await screen.findByRole('link', { name: 'Attention Is All You Need' })
  expect(link).toHaveAttribute('href', '/papers/p1')
  expect(screen.getByRole('link', { name: 'Exploiting input sanitization' })).toHaveAttribute('href', '/papers/p2')
})

test('Given the current route, Then its navigation item is marked active', async () => {
  mockApi({})
  renderApp('/settings')
  const nav = screen.getByRole('navigation', { name: 'Workspace' })
  expect(within(nav).getByRole('link', { name: 'New research' })).not.toHaveAttribute('data-active', 'true')
  expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('data-active', 'true')
})

test('Given /jobs from an old link, Then it redirects to Activity', async () => {
  mockApi({})
  renderApp('/jobs')
  await waitFor(() => expect(within(screen.getByRole('navigation', { name: 'Workspace' })).getByRole('link', { name: 'Activity' })).toHaveAttribute('data-active', 'true'))
})

test('Given a recent search, When removed from history, Then it is deleted and the list refreshes', async () => {
  let items = [search]
  const { calls } = mockApi({ 'GET /search-history': () => json({ items }), 'DELETE /search-history/s1': () => { items = []; return noContent() } })
  const { user } = renderApp('/')
  expect(await screen.findByRole('link', { name: 'regular expressions' })).toHaveAttribute('href', '/search?q=regular+expressions&provider=semantic_scholar')
  await user.click(screen.getByRole('button', { name: 'Options for regular expressions' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Remove from history' }))
  await waitFor(() => expect(screen.queryByRole('link', { name: 'regular expressions' })).not.toBeInTheDocument())
  expect(calls.some((call) => call.method === 'DELETE' && call.path === '/search-history/s1')).toBe(true)
})

test('Given history cannot load, Then the sidebar says so and retries on request', async () => {
  let failing = true
  mockApi({
    'GET /chats': () => failing ? json({ code: 'UNAVAILABLE', message: 'Down' }, 503) : json({ items: [] }),
    'GET /search-history': () => failing ? json({ code: 'UNAVAILABLE', message: 'Down' }, 503) : json({ items: [search] }),
  })
  const { user } = renderApp('/')
  expect(await screen.findByText(/History could not load/)).toBeVisible()
  failing = false
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('link', { name: 'regular expressions' })).toBeVisible()
})

test('Given Ctrl+K, Then the palette opens, finds a paper by title and opens its workspace', async () => {
  mockApi({ 'GET /papers': { items: [paper('p1', 'Attention Is All You Need')] }, 'GET /papers/p1': paper('p1', 'Attention Is All You Need') })
  const { user } = renderApp('/')
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
  const input = await screen.findByPlaceholderText('Search papers, conversations and actions')
  await user.type(input, 'attention')
  await user.click(await screen.findByRole('option', { name: /Attention Is All You Need/ }))
  expect(await screen.findByRole('heading', { name: 'Attention Is All You Need' })).toBeVisible()
  expect(screen.queryByPlaceholderText('Search papers, conversations and actions')).not.toBeInTheDocument()
})

test('Given the sidebar search entry, Then it opens the same palette', async () => {
  mockApi({})
  const { user } = renderApp('/')
  await user.click(screen.getByRole('button', { name: /Find papers and chats/ }))
  expect(await screen.findByRole('dialog', { name: 'Find papers and chats' })).toBeVisible()
})

test('Given a header slot, Then page controls render into it and nothing renders without one', () => {
  const slot = document.createElement('div')
  const { unmount } = renderWithProviders(<HeaderSlotContext.Provider value={slot}><ShellHeader><span>Paper title</span></ShellHeader></HeaderSlotContext.Provider>)
  expect(slot).toHaveTextContent('Paper title')
  unmount()
  renderWithProviders(<Routes><Route path="/" element={<ShellHeader><span>Orphan</span></ShellHeader>} /></Routes>)
  expect(screen.queryByText('Orphan')).not.toBeInTheDocument()
})

test('Given the mobile sidebar is open, When Escape is pressed once, Then the sheet closes', async () => {
  const original = window.matchMedia
  window.matchMedia = ((query: string) => ({ matches: query.includes('max-width'), media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia
  try {
    mockApi({})
    const { user } = renderApp('/')
    await user.click(screen.getByRole('button', { name: 'Toggle Sidebar' }))
    expect(await screen.findByRole('navigation', { name: 'Workspace' })).toBeVisible()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Workspace' })).not.toBeInTheDocument())
  } finally {
    window.matchMedia = original
  }
})

test('Given the desktop sidebar collapsed to icons, When an item is focused, Then its tooltip names it', async () => {
  mockApi({})
  const { user } = renderApp('/')
  await user.click(within(screen.getByRole('banner')).getByRole('button', { name: 'Toggle Sidebar' }))
  await waitFor(() => expect(document.querySelector('[data-slot="sidebar"][data-state="collapsed"]')).not.toBeNull())
  within(screen.getByRole('navigation', { name: 'Workspace' })).getByRole('link', { name: 'Library' }).focus()
  expect(await screen.findByRole('tooltip', { name: 'Library' })).toBeInTheDocument()
})
