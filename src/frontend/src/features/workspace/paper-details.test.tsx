// The ⓘ "Paper details" sheet (ARA-097): what the Details tab held, behind one button beside the paper's title.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

vi.mock('./PdfViewer', () => ({ default: ({ documentId }: { documentId: string }) => <p>{`Showing ${documentId}`}</p> }))
vi.mock('@/features/chat', () => ({ ConversationPane: () => <section aria-label="Conversation" /> }))

const paper = {
  id: 'p1',
  title: 'Evidence based research',
  authors: ['A. Author', 'B. Writer', 'C. Third'],
  year: 2024,
  venue: 'CHI',
  abstract: 'We study how readers verify generated answers against their sources.',
  doi: '10.1234/evidence',
  sources: [{ provider: 'openalex', external_id: 'W123', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, external_url: 'https://openalex.org/W123', pdf_url: null }],
  document_status: 'ready',
  active_document_id: 'doc-1',
  file_name: 'evidence.pdf',
  metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } },
}
const metadataOnly = { ...paper, document_status: 'metadata_only', active_document_id: null, file_name: null }

// jsdom has no layout, so react-resizable-panels would take every pointerdown for its split handle (see workspace.test).
const boundingRect = HTMLElement.prototype.getBoundingClientRect
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute('data-separator') ? new DOMRect(-500, -500, 1, 1) : boundingRect.call(this)
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function narrowScreen() {
  vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
    matches: query === '(max-width: 767px)', media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }))
}

async function openDetails(user: ReturnType<typeof renderApp>['user']) {
  await user.click(await screen.findByRole('button', { name: 'Paper details' }))
  return screen.findByRole('dialog', { name: paper.title })
}

test('Given the workspace header, Then ⓘ sits beside the title and status, and ARA-095’s ⋯ menu is gone from it', async () => {
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1')
  const title = await screen.findByRole('heading', { level: 1, name: paper.title })
  const header = title.parentElement!
  expect(within(header).getByText('Ready to read')).toBeVisible()
  expect(within(header).getByRole('button', { name: 'Paper details' })).toBeVisible()
  expect(screen.queryByRole('button', { name: `Actions for “${paper.title}”` })).not.toBeInTheDocument()
})

test('Given ⓘ is pressed, Then the sheet shows the citation, authors, actions, abstract, identifiers, sources, Advanced and Delete, in that order', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(within(sheet).getByRole('heading', { level: 2, name: paper.title })).toBeVisible()
  // The citation is the sheet's description; the full author list follows it.
  expect(sheet).toHaveAccessibleDescription(/^Author et al\. \(2024\),\s?CHI$/)
  expect(within(sheet).getByText('A. Author, B. Writer, C. Third')).toBeVisible()
  expect(within(sheet).getByRole('button', { name: 'Edit details' })).toBeVisible()
  expect(within(sheet).getByRole('button', { name: 'Look up again' })).toBeVisible()
  expect(within(sheet).getByRole('link', { name: /^DOI/ })).toHaveAttribute('href', 'https://doi.org/10.1234/evidence')
  expect(within(sheet).getByRole('link', { name: /^OpenAlex/ })).toHaveAttribute('href', 'https://openalex.org/W123')
  expect(within(sheet).getByText(paper.abstract)).toBeVisible()
  const identifiers = within(sheet).getByRole('region', { name: 'Identifiers' })
  expect(within(identifiers).getByText('10.1234/evidence')).toHaveClass('font-mono')
  expect(within(identifiers).getByText('W123')).toHaveClass('font-mono')
  const sources = within(sheet).getByRole('region', { name: 'Where this information came from' })
  expect([...sources.querySelectorAll('dt, dd')].map((cell) => cell.textContent)).toEqual(['Title', 'Edited by you', 'Authors', 'OpenAlex'])
  expect(within(sheet).getByRole('button', { name: 'Advanced' })).toHaveAttribute('aria-expanded', 'false')
  // Section order: actions, abstract, identifiers, sources, Advanced, then the destructive action last.
  const order = ['Edit details', 'Abstract', 'Identifiers', 'Where this information came from', 'Advanced', 'Delete paper…'].map((name) => within(sheet).getAllByText(name)[0]!)
  for (let index = 1; index < order.length; index += 1) {
    expect(order[index - 1]!.compareDocumentPosition(order[index]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
})

test('Given the sheet, When Esc is pressed, Then it closes and focus returns to ⓘ', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await openDetails(user)
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Paper details' })).toHaveFocus()
})

test('Given the sheet opened from the keyboard, When its close button is pressed, Then focus returns to ⓘ', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  const trigger = await screen.findByRole('button', { name: 'Paper details' })
  trigger.focus()
  await user.keyboard('{Enter}')
  const sheet = await screen.findByRole('dialog', { name: paper.title })
  await user.click(within(sheet).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(trigger).toHaveFocus()
})

test('Given the sheet, When the user clicks outside it, Then it closes', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await openDetails(user)
  const overlay = document.querySelector('[data-slot="sheet-overlay"]')!
  fireEvent.pointerDown(overlay)
  fireEvent.pointerUp(overlay)
  fireEvent.click(overlay)
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

test('Given a long abstract, Then it is clamped with Show more', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(within(sheet).getByText(paper.abstract)).toHaveClass('line-clamp-3')
})

test('Given identifiers, When Copy DOI is pressed, Then the DOI is copied and the button says so', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  await user.click(within(sheet).getByRole('button', { name: 'Copy DOI' }))
  expect(writeText).toHaveBeenCalledWith('10.1234/evidence')
  expect(await within(sheet).findByRole('button', { name: 'Copied' })).toBeVisible()
})

test('Given Edit details in the sheet, When only the venue changes, Then only the venue is patched and the sheet shows it', async () => {
  let stored = paper
  const { calls } = mockApi({ 'GET /papers/p1': () => json(stored), 'PATCH /papers/p1': ({ body }) => json(stored = { ...stored, ...(body as object) }) })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  await user.click(within(sheet).getByRole('button', { name: 'Edit details' }))
  const editor = await screen.findByRole('dialog', { name: 'Edit details' })
  const venue = within(editor).getByRole('textbox', { name: 'Venue' })
  await user.clear(venue)
  await user.type(venue, 'CHI 2024')
  await user.click(within(editor).getByRole('button', { name: 'Save details' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Edit details' })).not.toBeInTheDocument())
  expect(await within(screen.getByRole('dialog', { name: paper.title })).findByText('CHI 2024')).toBeVisible()
  expect(calls.filter((call) => call.method === 'PATCH').map((call) => call.body)).toEqual([{ venue: 'CHI 2024' }])
})

test('Given the catalog lookup ran out of attempts, When Look up again is pressed, Then the sheet explains it and queues one lookup', async () => {
  const failed = { id: 'lookup-2', kind: 'metadata', state: 'failed', stage: 'failed', progress: 50, error: { code: 'PROVIDER_RATE_LIMITED', message: 'The metadata sources are rate limited, so the details read from the PDF were kept.' }, result: null, attempts: 3, paper_id: 'p1', paper_title: paper.title, created_at: '2026-10-09T00:00:00Z' }
  const queued = { ...failed, id: 'lookup-3', state: 'queued', stage: 'queued', error: null, attempts: 0 }
  let lookups: object[] = [failed]
  const { calls } = mockApi({ 'GET /papers/p1': paper, 'GET /jobs': ({ url }) => json({ items: url.searchParams.get('kind') === 'metadata' ? lookups : [] }), 'POST /papers/p1/metadata-lookup': () => { lookups = [queued, failed]; return json(queued, 202) } })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(await within(sheet).findByText(/the details read from the PDF were kept/)).toBeVisible()
  expect(within(sheet).getByText('Refreshes the details from the metadata source. Fields you edited stay as they are.')).toBeVisible()
  await user.click(within(sheet).getByRole('button', { name: 'Look up again' }))
  expect(await within(sheet).findByRole('button', { name: 'Looking up…' })).toBeDisabled()
  expect(calls.filter((call) => call.method === 'POST' && call.path === '/papers/p1/metadata-lookup')).toHaveLength(1)
})

test('Given a metadata-only paper, Then the sheet has no Advanced search index and says when the abstract is missing', async () => {
  mockApi({ 'GET /papers/p1': { ...metadataOnly, abstract: null } })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(within(sheet).getByText('No abstract is available for this paper yet.')).toBeVisible()
  expect(within(sheet).queryByRole('button', { name: 'Advanced' })).not.toBeInTheDocument()
})

test('Given a ready paper, When Advanced is opened, Then the search index loads and can be rebuilt', async () => {
  const profile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null, price_per_million: 0.13 }
  const retrieval = { paper_id: 'p1', document_id: 'doc-1', effective_profile: profile.key, parser: 'pymupdf4llm', chunk_count: 212, section_count: 14, mode: 'hybrid', mode_note: null, indexes: [{ profile: profile.key, state: 'ready', embedded: 212, total: 212, updated_at: '2026-10-09T12:00:00Z', error: null }] }
  const { calls } = mockApi({ 'GET /papers/p1': paper, 'GET /retrieval/profiles': { items: [profile], default_profile: profile.key }, 'GET /papers/p1/retrieval': retrieval })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(calls.some((call) => call.path.includes('retrieval'))).toBe(false)
  await user.click(within(sheet).getByRole('button', { name: 'Advanced' }))
  expect(await within(sheet).findByText('212 passages · 14 sections')).toBeVisible()
  expect(within(sheet).getByRole('heading', { name: 'Search index' })).toBeVisible()
  expect(within(sheet).getByRole('button', { name: 'Rebuild index' })).toBeEnabled()
})

test('Given the sheet, When Delete paper… is confirmed, Then the Library opens and says so', async () => {
  let deleted = false
  const { calls } = mockApi({
    'GET /papers/p1': () => deleted ? json({ code: 'PAPER_NOT_FOUND', message: 'Paper not found.' }, 404) : json(paper),
    'GET /papers/p1/deletion-preview': { papers: [{ paper_id: 'p1', title: paper.title }], missing: [], pdfs: 1, summaries: 0, deleted_chats: [], updated_chats: [], active_jobs: 0, answering: false },
    'DELETE /papers/p1': () => { deleted = true; return new Response(null, { status: 204 }) },
  })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  await user.click(within(sheet).getByRole('button', { name: 'Delete paper…' }))
  const dialog = await screen.findByRole('alertdialog', { name: `Delete “${paper.title}”?` })
  await user.click(await within(dialog).findByRole('button', { name: 'Delete paper' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual(['/papers/p1'])
})

test('Given a PDF whose DOI belongs to another library paper, Then the sheet says so with a link', async () => {
  mockApi({ 'GET /papers/p1': { ...paper, pdf_doi_owner: { paper_id: 'p-lib', title: 'The library paper' } } })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(within(sheet).getByText('This PDF’s DOI belongs to “The library paper” in your library.')).toBeVisible()
  expect(within(sheet).getByRole('link', { name: 'Open that paper' })).toHaveAttribute('href', '/papers/p-lib')
})

test('Given a narrow screen, When ⓘ is pressed, Then the details open as a bottom sheet', async () => {
  narrowScreen()
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  expect(sheet).toHaveAttribute('data-side', 'bottom')
})

test('Given a long venue, Then the sheet shows it in full instead of truncating it', async () => {
  const venue = 'Proceedings of the ACM Conference on Human Factors in Computing Systems'
  mockApi({ 'GET /papers/p1': { ...paper, venue } })
  const { user } = renderApp('/papers/p1')
  const sheet = await openDetails(user)
  const cite = within(sheet).getByText(venue)
  expect(cite.tagName).toBe('CITE')
  expect(cite).not.toHaveClass('truncate')
})
