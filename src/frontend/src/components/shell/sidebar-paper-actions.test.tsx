// Paper actions behind a hover "…" in the sidebar's Papers list (ARA-103).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import { mockApi, noContent } from '@/test/fetch-routes'
import { testClient } from '@/test/render'

const paper = (id: string, title: string) => ({ id, title, authors: ['Ada Researcher'], year: 2024, abstract: null, doi: null, venue: null, sources: [], document_status: 'ready', active_document_id: `d-${id}`, metadata_provenance: {} })
const attention = paper('p1', 'Attention is all you need')
const sanitization = paper('p2', 'Exploiting input sanitization')
const preview = (id: string, title: string) => ({ papers: [{ paper_id: id, title }], missing: [], pdfs: 1, summaries: 0, deleted_chats: [], updated_chats: [], active_jobs: 0, answering: false })
afterEach(() => vi.unstubAllGlobals())

function LocationProbe() { const location = useLocation(); return <output aria-label="Location">{location.pathname}</output> }
function mount(path: string) {
  const user = userEvent.setup()
  render(<QueryClientProvider client={testClient()}><MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter></QueryClientProvider>)
  return { user }
}
const routes = () => ({
  'GET /papers': { items: [attention, sanitization] },
  'GET /papers/p1': attention,
  'GET /papers/p2': sanitization,
  'GET /papers/p1/deletion-preview': preview('p1', attention.title),
  'GET /papers/p2/deletion-preview': preview('p2', sanitization.title),
})

/** The sidebar's own row, since the workspace header carries the same menu for the open paper. */
async function sidebarTrigger(title: string) {
  const link = await screen.findByRole('link', { name: new RegExp(title) })
  return within(link.closest('li') as HTMLElement).getByRole('button', { name: `Actions for “${title}”` })
}

test('Given the sidebar papers, Then each row holds an actions button after its link', async () => {
  mockApi(routes())
  mount('/')
  const trigger = await sidebarTrigger(attention.title)
  expect(trigger).toHaveAttribute('data-sidebar', 'menu-action')
})

test('Given a sidebar paper menu, When opened, Then it offers the Library actions and Edit details opens the dialog', async () => {
  mockApi(routes())
  const { user } = mount('/')
  await user.click(await sidebarTrigger(attention.title))
  const menu = await screen.findByRole('menu')
  expect(within(menu).getByRole('menuitem', { name: 'Edit details' })).toBeVisible()
  expect(within(menu).getByRole('menuitem', { name: 'Delete…' })).toBeVisible()
  await user.click(within(menu).getByRole('menuitem', { name: 'Edit details' }))
  expect(await screen.findByRole('dialog', { name: 'Edit details' })).toBeVisible()
})

test('Given the open paper, When deleted from the sidebar, Then the app goes home', async () => {
  const { calls } = mockApi({ ...routes(), 'DELETE /papers/p1': () => noContent() })
  const { user } = mount('/papers/p1')
  await user.click(await sidebarTrigger(attention.title))
  await user.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Delete…' }))
  await user.click(await within(await screen.findByRole('alertdialog')).findByRole('button', { name: 'Delete paper' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'DELETE' && call.path === '/papers/p1')).toBe(true))
  await waitFor(() => expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/$/))
})

test('Given another paper is open, When a different one is deleted from the sidebar, Then the page stays', async () => {
  const { calls } = mockApi({ ...routes(), 'DELETE /papers/p2': () => noContent() })
  const { user } = mount('/papers/p1')
  await user.click(await sidebarTrigger(sanitization.title))
  await user.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Delete…' }))
  await user.click(await within(await screen.findByRole('alertdialog')).findByRole('button', { name: 'Delete paper' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'DELETE' && call.path === '/papers/p2')).toBe(true))
  expect(screen.getByLabelText('Location')).toHaveTextContent('/papers/p1')
})
