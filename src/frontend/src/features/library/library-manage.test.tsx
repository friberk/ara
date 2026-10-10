// Deleting papers and editing their details from the Library (ARA-095).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import { json, mockApi, noContent } from '@/test/fetch-routes'
import { testClient } from '@/test/render'

const attention = { id: 'p1', title: 'Attention is all you need', authors: ['Ashish Vaswani'], year: 2017, abstract: null, doi: '10.48550/arXiv.1706.03762', venue: 'NeurIPS', sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const sanitization = { ...attention, id: 'p2', title: 'Exploiting input sanitization', doi: null, venue: null, document_status: 'metadata_only', active_document_id: null }
const preview = {
  papers: [{ paper_id: 'p1', title: attention.title }],
  missing: [],
  pdfs: 2,
  summaries: 1,
  deleted_chats: [{ id: 'c1', title: 'What is attention?' }],
  updated_chats: [{ id: 'c2', title: 'Transformers compared' }],
  active_jobs: 1,
  answering: false,
}
afterEach(() => vi.unstubAllGlobals())

function LocationProbe() { const location = useLocation(); return <output aria-label="Location">{`${location.pathname}${location.search}`}</output> }
function mount(path = '/library') {
  const user = userEvent.setup()
  render(<QueryClientProvider client={testClient()}><MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter></QueryClientProvider>)
  return { user }
}

/** The library answers with the papers still stored, so deleted rows go after the refresh. */
function library(initial = [attention, sanitization]) {
  let papers = initial
  return {
    routes: { 'GET /papers': () => json({ items: papers }) },
    remove: (ids: string[]) => { papers = papers.filter((paper) => !ids.includes(paper.id)) },
  }
}

async function rowActions(user: ReturnType<typeof userEvent.setup>, title: string) {
  // The sidebar's Papers list has the same menu (ARA-103), so look in the Library itself.
  await user.click(await within(await screen.findByRole('main')).findByRole('button', { name: `Actions for “${title}”` }))
  return screen.getByRole('menu')
}

test('Given a library row, When Delete is chosen, Then the dialog lists what goes and nothing is deleted until confirmed', async () => {
  const store = library()
  const { calls } = mockApi({
    ...store.routes,
    'GET /papers/p1/deletion-preview': preview,
    'DELETE /papers/p1': () => { store.remove(['p1']); return noContent() },
  })
  const { user } = mount()
  await user.click(within(await rowActions(user, attention.title)).getByRole('menuitem', { name: 'Delete…' }))

  const dialog = await screen.findByRole('alertdialog', { name: `Delete “${attention.title}”?` })
  const removed = await within(dialog).findByRole('list', { name: 'What will be deleted' })
  expect(within(removed).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    'The paper and its details',
    '2 PDFs, with their text and search index',
    '1 summary',
    '1 conversation about only this paper: “What is attention?”',
  ])
  expect(within(dialog).getByText('1 conversation that includes other papers keeps them and loses this one. Its earlier answers stay readable.')).toBeVisible()
  expect(within(dialog).getByText('1 background task for this paper stops.')).toBeVisible()
  expect(within(dialog).getByText('This can’t be undone.')).toBeVisible()
  await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false)

  await user.click(within(await rowActions(user, attention.title)).getByRole('menuitem', { name: 'Delete…' }))
  const again = await screen.findByRole('alertdialog')
  await user.click(await within(again).findByRole('button', { name: 'Delete paper' }))
  await waitFor(() => expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual(['/papers/p1']))
  expect(await screen.findByText(`Deleted “${attention.title}”`)).toBeVisible()
  // The row and the sidebar's paper list both drop it.
  await waitFor(() => expect(screen.queryAllByRole('link', { name: new RegExp(`^${attention.title}, `) })).toHaveLength(0))
  expect(within(screen.getByRole('main')).getByRole('link', { name: new RegExp(`^${sanitization.title}, `) })).toBeVisible()
})

test('Given several selected papers, When they are deleted, Then one dialog previews them all and its button names the count', async () => {
  const store = library()
  const combined = { ...preview, papers: [{ paper_id: 'p1', title: attention.title }, { paper_id: 'p2', title: sanitization.title }], pdfs: 2, summaries: 1, deleted_chats: [], updated_chats: [], active_jobs: 0 }
  const { calls } = mockApi({
    ...store.routes,
    'POST /papers/deletion-preview': combined,
    'POST /papers/delete': ({ body }) => { const ids = (body as { paper_ids: string[] }).paper_ids; store.remove(ids); return json({ deleted: ids, missing: [] }) },
  })
  const { user } = mount()
  await user.click(await screen.findByRole('checkbox', { name: `Select “${attention.title}”` }))
  const toolbar = screen.getByRole('toolbar', { name: 'Selected papers' })
  expect(within(toolbar).getByText('1 selected')).toBeVisible()
  await user.click(screen.getByRole('checkbox', { name: `Select “${sanitization.title}”` }))
  expect(within(toolbar).getByText('2 selected')).toBeVisible()
  await user.click(within(toolbar).getByRole('button', { name: 'Delete…' }))

  const dialog = await screen.findByRole('alertdialog', { name: 'Delete 2 papers?' })
  const removed = await within(dialog).findByRole('list', { name: 'What will be deleted' })
  expect(within(removed).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    '2 papers and their details',
    '2 PDFs, with their text and search index',
    '1 summary',
  ])
  expect(calls.find((call) => call.path === '/papers/deletion-preview')?.body).toEqual({ paper_ids: ['p1', 'p2'] })
  await user.click(within(dialog).getByRole('button', { name: 'Delete 2 papers' }))
  await waitFor(() => expect(calls.find((call) => call.path === '/papers/delete')?.body).toEqual({ paper_ids: ['p1', 'p2'] }))
  expect(await screen.findByText('Deleted 2 papers')).toBeVisible()
  expect(await screen.findByRole('heading', { name: 'Your library is empty' })).toBeVisible()
  expect(screen.queryByRole('toolbar', { name: 'Selected papers' })).not.toBeInTheDocument()
})

test('Given the select-all box, Then it selects every listed paper and clears them again', async () => {
  mockApi(library().routes)
  const { user } = mount()
  const all = await screen.findByRole('checkbox', { name: 'Select all papers' })
  await user.click(all)
  expect(within(screen.getByRole('toolbar', { name: 'Selected papers' })).getByText('2 selected')).toBeVisible()
  expect(screen.getByRole('checkbox', { name: `Select “${sanitization.title}”` })).toBeChecked()
  await user.click(screen.getByRole('button', { name: 'Clear selection' }))
  expect(screen.queryByRole('toolbar', { name: 'Selected papers' })).not.toBeInTheDocument()
  expect(all).not.toBeChecked()
})

test('Given a conversation still writing an answer, Then the dialog says to wait and cannot delete yet', async () => {
  const { calls } = mockApi({ ...library().routes, 'GET /papers/p1/deletion-preview': { ...preview, answering: true } })
  const { user } = mount()
  await user.click(within(await rowActions(user, attention.title)).getByRole('menuitem', { name: 'Delete…' }))
  const dialog = await screen.findByRole('alertdialog')
  expect(await within(dialog).findByText('A conversation about this paper is still writing an answer. Delete the paper when it finishes.')).toBeVisible()
  expect(within(dialog).getByRole('button', { name: 'Delete paper' })).toBeDisabled()
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
})

test('Given a library row, When Edit details is chosen, Then a dialog edits every field and sends only what changed', async () => {
  let stored = attention
  const { calls } = mockApi({
    'GET /papers': () => json({ items: [stored, sanitization] }),
    'PATCH /papers/p1': ({ body }) => json(stored = { ...stored, ...(body as object), metadata_provenance: { venue: { source: 'manual', value: 'NeurIPS 2017' } } }),
  })
  const { user } = mount()
  await user.click(within(await rowActions(user, attention.title)).getByRole('menuitem', { name: 'Edit details' }))
  const dialog = await screen.findByRole('dialog', { name: 'Edit details' })
  for (const field of ['Title', 'Authors', 'Publication year', 'Venue', 'DOI', 'Abstract']) expect(within(dialog).getByRole('textbox', { name: field })).toBeVisible()
  const venue = within(dialog).getByRole('textbox', { name: 'Venue' })
  expect(venue).toHaveValue('NeurIPS')
  await user.clear(venue)
  await user.type(venue, 'NeurIPS 2017')
  await user.click(within(dialog).getByRole('button', { name: 'Save details' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(calls.filter((call) => call.method === 'PATCH').map((call) => call.body)).toEqual([{ venue: 'NeurIPS 2017' }])
  expect(await screen.findByText('Details saved')).toBeVisible()
})

test('Given a library row, When Look up details again is chosen, Then the lookup is queued', async () => {
  const { calls } = mockApi({ ...library().routes, 'POST /papers/p1/metadata-lookup': () => json({ id: 'job-1', kind: 'metadata', state: 'queued', stage: 'queued', progress: 0 }, 202) })
  const { user } = mount()
  await user.click(within(await rowActions(user, attention.title)).getByRole('menuitem', { name: 'Look up details again' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/papers/p1/metadata-lookup')).toBe(true))
  expect(await screen.findByText('Looking up the paper’s details. Fields you edited stay as they are.')).toBeVisible()
})

test('Given a link to a deleted paper, Then the workspace returns to the Library with a short note', async () => {
  mockApi({ ...library([sanitization]).routes, 'GET /papers/p1': () => json({ code: 'PAPER_NOT_FOUND', message: 'Paper not found.' }, 404) })
  const { user } = mount('/papers/p1')
  expect(await screen.findByText('That paper isn’t in your library anymore. It may have been deleted.')).toBeVisible()
  expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/library$/)
  expect(screen.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Dismiss' }))
  expect(screen.queryByText('That paper isn’t in your library anymore. It may have been deleted.')).not.toBeInTheDocument()
})
