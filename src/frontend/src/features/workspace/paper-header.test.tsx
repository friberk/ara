// The paper header above the PDF and the ⓘ dialog behind it (ARA-101). The user wanted the bibliography back on top
// of the reader, as the old Details tab showed it, and ⓘ to keep only provenance and search details.
import { screen, waitFor, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

// The stand-in renders the header it is given above its pages, as the real viewer does inside its scroll column.
vi.mock('./PdfViewer', () => ({
  default: ({ documentId, header }: { documentId: string; header?: React.ReactNode }) => (
    <div role="region" aria-label="PDF document">{header}<p>{`Showing ${documentId}`}</p></div>
  ),
}))

const other: Citation = { chunk_id: 'chunk-9', document_id: 'doc-2', paper_id: 'p2', page: 3, excerpt: 'Dense recall is 0.79.' }
vi.mock('@/features/chat', async () => {
  const { useWorkspace } = await import('./workspace-context')
  return {
    ConversationPane: function ConversationStub() {
      const { showSource } = useWorkspace()
      return <section aria-label="Conversation"><button type="button" onClick={() => showSource(other)}>Cite the second paper</button></section>
    },
  }
})

const paper = {
  id: 'p1',
  title: 'Evidence based research',
  authors: ['A. Author', 'B. Writer', 'C. Third'],
  year: 2024,
  venue: 'Proceedings of the ACM Conference on Human Factors in Computing Systems',
  abstract: 'We study how readers verify generated answers against their sources.',
  doi: '10.1234/evidence',
  sources: [{ provider: 'openalex', external_id: 'W123', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, external_url: 'https://openalex.org/W123', pdf_url: null }],
  document_status: 'ready',
  active_document_id: 'doc-1',
  file_name: 'evidence.pdf',
  metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } },
}
const sparse = { ...paper, title: 'Untitled notes', authors: [], year: null, venue: null, abstract: null, doi: null, sources: [], metadata_provenance: {} }
const second = { ...paper, id: 'p2', title: 'Dense passage retrieval', authors: ['Vladimir Karpukhin', 'Barlas Oguz'], year: 2020, venue: 'EMNLP', abstract: 'Dense retrieval beats sparse retrieval.', doi: null, sources: [], active_document_id: 'doc-2' }

// The ⓘ dialog loads the paper's search index when it opens.
const profile = { key: 'openai-3-large', provider: 'openai', model_id: 'text-embedding-3-large', display_name: 'OpenAI text-embedding-3-large', dimensions: 3072, status: 'available', unavailable_reason: null, local_model_key: null, price_per_million: 0.13 }
const retrieval = { paper_id: 'p1', document_id: 'doc-1', effective_profile: profile.key, parser: 'pymupdf4llm', chunk_count: 212, section_count: 14, mode: 'hybrid', mode_note: null, indexes: [{ profile: profile.key, state: 'ready', embedded: 212, total: 212, updated_at: '2026-10-09T12:00:00Z', error: null }] }
const index = { 'GET /retrieval/profiles': { items: [profile], default_profile: profile.key }, 'GET /papers/p1/retrieval': retrieval, 'GET /papers/p2/retrieval': { ...retrieval, paper_id: 'p2', document_id: 'doc-2' } }

const boundingRect = HTMLElement.prototype.getBoundingClientRect
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute('data-separator') ? new DOMRect(-500, -500, 1, 1) : boundingRect.call(this)
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const header = async (name = paper.title) => (await screen.findByRole('heading', { level: 2, name })).closest('header') as HTMLElement

test('Given a paper with its PDF, Then the reader opens with its bibliography above the PDF, inside the scrolling document', async () => {
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1')
  // pdf.js loads lazily; the header shows meanwhile and then sits inside the PDF's own scroll column.
  const document = await screen.findByRole('region', { name: 'PDF document' })
  const top = within(document).getByRole('heading', { level: 2, name: paper.title }).closest('header') as HTMLElement
  expect(within(top).getByText('A. Author, B. Writer, C. Third')).toBeVisible()
  expect(within(top).getByText('2024', { exact: false }).closest('p')).toHaveTextContent(/^2024,\sProceedings of the ACM Conference on Human Factors in Computing Systems$/)
  expect(within(top).getByText(paper.venue).tagName).toBe('CITE')
  expect(within(top).getByRole('link', { name: /^DOI/ })).toHaveAttribute('href', 'https://doi.org/10.1234/evidence')
  expect(within(top).getByRole('link', { name: /^OpenAlex/ })).toHaveAttribute('href', 'https://openalex.org/W123')
  expect(within(top).getByText(paper.abstract)).toHaveClass('line-clamp-3')
  // The abstract has its own small heading, grouped with its text (ARA-101 follow-up).
  const abstract = within(top).getByRole('heading', { level: 3, name: 'Abstract' })
  expect(abstract).toHaveClass('text-sm', 'font-medium')
  expect(abstract.nextElementSibling).toContainElement(within(top).getByText(paper.abstract))
  expect(within(top).getByRole('button', { name: 'Edit details' })).toBeVisible()
  expect(within(top).getByRole('button', { name: 'Sources and search index' })).toBeVisible()
  // The PDF follows the header in the same scrolling column.
  expect(top.compareDocumentPosition(screen.getByText('Showing doc-1')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('Given a sparse paper, Then the header shows what exists and says plainly that the abstract is missing', async () => {
  mockApi({ 'GET /papers/p1': sparse })
  renderApp('/papers/p1')
  const top = await header('Untitled notes')
  expect(within(top).getByText('No abstract is available for this paper yet.')).toBeVisible()
  expect(within(top).getByRole('heading', { level: 3, name: 'Abstract' }).nextElementSibling).toHaveTextContent('No abstract is available for this paper yet.')
  expect(within(top).queryByRole('list', { name: 'Links' })).not.toBeInTheDocument()
  expect(within(top).queryByText(/Not available|null|undefined/)).not.toBeInTheDocument()
  expect(top.querySelectorAll('p').length).toBe(1)
})

test('Given the top bar, Then it keeps the title, and ⓘ lives in the paper header instead', async () => {
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1')
  expect(await screen.findByRole('heading', { level: 1, name: paper.title })).toBeVisible()
  await header()
  expect(screen.getAllByRole('button', { name: 'Sources and search index' })).toHaveLength(1)
  expect(screen.queryByRole('button', { name: 'Paper details' })).not.toBeInTheDocument()
})

test('Given a paper without a PDF, Then the same header sits above the ways to get one, and the abstract shows once', async () => {
  mockApi({ 'GET /papers/p1': { ...paper, document_status: 'metadata_only', active_document_id: null, file_name: null } })
  renderApp('/papers/p1')
  const top = await header()
  const reader = screen.getByRole('region', { name: 'PDF reader' })
  const attach = await within(reader).findByText('Attach the PDF to read, summarize and ask')
  expect(top.compareDocumentPosition(attach) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(within(reader).getAllByText(paper.abstract)).toHaveLength(1)
})

test('Given a reader tab for another paper, When it is active, Then the header describes that paper', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /papers/p2': second })
  const { user } = renderApp('/papers/p1')
  await header()
  await user.click(screen.getByRole('button', { name: 'Cite the second paper' }))
  const visible = await waitFor(() => {
    const found = screen.getAllByRole('heading', { level: 2 }).filter((heading) => heading.closest('[hidden]') === null)
    expect(found.map((heading) => heading.textContent)).toEqual([second.title])
    return found[0]!.closest('header') as HTMLElement
  })
  expect(within(visible).getByText('Vladimir Karpukhin, Barlas Oguz')).toBeVisible()
  expect(within(visible).getByText(second.abstract)).toBeVisible()
})

test('Given ⓘ, When it is pressed, Then a centred dialog lists sources, Look up again, identifiers and the search index, and none of the bibliography', async () => {
  const { calls } = mockApi({ 'GET /papers/p1': paper, ...index })
  const { user } = renderApp('/papers/p1')
  const top = await header()
  expect(calls.some((call) => call.path.includes('retrieval'))).toBe(false)
  await user.click(within(top).getByRole('button', { name: 'Sources and search index' }))
  const dialog = await screen.findByRole('dialog', { name: 'Sources and search index' })
  expect(dialog).not.toHaveAttribute('data-side')
  const sources = within(dialog).getByRole('region', { name: 'Where this information came from' })
  expect([...sources.querySelectorAll('dt, dd')].map((cell) => cell.textContent)).toEqual(['Title', 'Edited by you', 'Authors', 'OpenAlex'])
  expect(within(dialog).getByRole('button', { name: 'Look up again' })).toBeVisible()
  expect(within(dialog).getByText('Refreshes the details from the metadata source. Fields you edited stay as they are.')).toBeVisible()
  const identifiers = within(dialog).getByRole('region', { name: 'Identifiers' })
  expect(within(identifiers).getByText('10.1234/evidence')).toHaveClass('font-mono')
  expect(within(identifiers).getByText('W123')).toHaveClass('font-mono')
  expect(await within(dialog).findByText('Searching 212 passages in 14 sections with OpenAI text-embedding-3-large.')).toBeVisible()
  expect(within(dialog).getByRole('heading', { name: 'Search index' })).toBeVisible()
  expect(within(dialog).getByRole('button', { name: 'Delete paper…' })).toBeVisible()
  expect(within(dialog).queryByText(paper.abstract)).not.toBeInTheDocument()
  expect(within(dialog).queryByText('A. Author, B. Writer, C. Third')).not.toBeInTheDocument()
})

test('Given the ⓘ dialog, When Esc or its close button is used, Then focus returns to ⓘ', async () => {
  mockApi({ 'GET /papers/p1': paper, ...index })
  const { user } = renderApp('/papers/p1')
  const info = within(await header()).getByRole('button', { name: 'Sources and search index' })
  await user.click(info)
  await screen.findByRole('dialog', { name: 'Sources and search index' })
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(info).toHaveFocus()
  await user.keyboard('{Enter}')
  const dialog = await screen.findByRole('dialog', { name: 'Sources and search index' })
  await user.click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(info).toHaveFocus()
})

test('Given identifiers in the dialog, When Copy DOI is pressed, Then the DOI is copied', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  mockApi({ 'GET /papers/p1': paper, ...index })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await header()).getByRole('button', { name: 'Sources and search index' }))
  const dialog = await screen.findByRole('dialog', { name: 'Sources and search index' })
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  await user.click(within(dialog).getByRole('button', { name: 'Copy DOI' }))
  expect(writeText).toHaveBeenCalledWith('10.1234/evidence')
  expect(await within(dialog).findByRole('button', { name: 'Copied' })).toBeVisible()
})

test('Given the failed catalog lookup, When Look up again is pressed in the dialog, Then one lookup is queued', async () => {
  const failed = { id: 'lookup-2', kind: 'metadata', state: 'failed', stage: 'failed', progress: 50, error: { code: 'PROVIDER_RATE_LIMITED', message: 'The metadata sources are rate limited, so the details read from the PDF were kept.' }, result: null, attempts: 3, paper_id: 'p1', paper_title: paper.title, created_at: '2026-10-09T00:00:00Z' }
  const queued = { ...failed, id: 'lookup-3', state: 'queued', stage: 'queued', error: null, attempts: 0 }
  let lookups: object[] = [failed]
  const { calls } = mockApi({ 'GET /papers/p1': paper, ...index, 'GET /jobs': ({ url }) => json({ items: url.searchParams.get('kind') === 'metadata' ? lookups : [] }), 'POST /papers/p1/metadata-lookup': () => { lookups = [queued, failed]; return json(queued, 202) } })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await header()).getByRole('button', { name: 'Sources and search index' }))
  const dialog = await screen.findByRole('dialog', { name: 'Sources and search index' })
  expect(await within(dialog).findByText(/the details read from the PDF were kept/)).toBeVisible()
  await user.click(within(dialog).getByRole('button', { name: 'Look up again' }))
  expect(await within(dialog).findByRole('button', { name: 'Looking up…' })).toBeDisabled()
  expect(calls.filter((call) => call.method === 'POST' && call.path === '/papers/p1/metadata-lookup')).toHaveLength(1)
})

test('Given Edit details in the header, When only the venue changes, Then only the venue is patched and the header shows it', async () => {
  let stored = paper
  const { calls } = mockApi({ 'GET /papers/p1': () => json(stored), 'PATCH /papers/p1': ({ body }) => json(stored = { ...stored, ...(body as object) }) })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await header()).getByRole('button', { name: 'Edit details' }))
  const editor = await screen.findByRole('dialog', { name: 'Edit details' })
  const venue = within(editor).getByRole('textbox', { name: 'Venue' })
  await user.clear(venue)
  await user.type(venue, 'CHI 2024')
  await user.click(within(editor).getByRole('button', { name: 'Save details' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Edit details' })).not.toBeInTheDocument())
  expect(await within(await header()).findByText('CHI 2024')).toBeVisible()
  expect(calls.filter((call) => call.method === 'PATCH').map((call) => call.body)).toEqual([{ venue: 'CHI 2024' }])
})

test('Given the dialog, When Delete paper… is confirmed, Then the Library opens', async () => {
  let deleted = false
  const { calls } = mockApi({
    'GET /papers/p1': () => deleted ? json({ code: 'PAPER_NOT_FOUND', message: 'Paper not found.' }, 404) : json(paper),
    ...index,
    'GET /papers/p1/deletion-preview': { papers: [{ paper_id: 'p1', title: paper.title }], missing: [], pdfs: 1, summaries: 0, deleted_chats: [], updated_chats: [], active_jobs: 0, answering: false },
    'DELETE /papers/p1': () => { deleted = true; return new Response(null, { status: 204 }) },
  })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await header()).getByRole('button', { name: 'Sources and search index' }))
  await user.click(within(await screen.findByRole('dialog', { name: 'Sources and search index' })).getByRole('button', { name: 'Delete paper…' }))
  await user.click(await within(await screen.findByRole('alertdialog', { name: `Delete “${paper.title}”?` })).findByRole('button', { name: 'Delete paper' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual(['/papers/p1'])
})

test('Given another paper’s tab, Then its dialog has no Delete paper, which stays with the workspace’s own paper', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /papers/p2': second, ...index })
  const { user } = renderApp('/papers/p1')
  await header()
  await user.click(screen.getByRole('button', { name: 'Cite the second paper' }))
  const visible = await waitFor(() => {
    const found = screen.getAllByRole('heading', { level: 2 }).filter((heading) => heading.closest('[hidden]') === null)
    expect(found.map((heading) => heading.textContent)).toEqual([second.title])
    return found[0]!.closest('header') as HTMLElement
  })
  await user.click(within(visible).getByRole('button', { name: 'Sources and search index' }))
  const dialog = await screen.findByRole('dialog', { name: 'Sources and search index' })
  expect(within(dialog).queryByRole('button', { name: 'Delete paper…' })).not.toBeInTheDocument()
})

test('Given a PDF whose DOI belongs to another library paper, Then the header says so with a link', async () => {
  mockApi({ 'GET /papers/p1': { ...paper, pdf_doi_owner: { paper_id: 'p-lib', title: 'The library paper' } } })
  renderApp('/papers/p1')
  const top = await header()
  expect(within(top).getByText('This PDF’s DOI belongs to “The library paper” in your library.')).toBeVisible()
  expect(within(top).getByRole('link', { name: 'Open that paper' })).toHaveAttribute('href', '/papers/p-lib')
})

test('Given a narrow reader, Then Edit details shrinks to its icon and keeps its name, so the title keeps the width (visual check, 390px)', async () => {
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1')
  const edit = within(await header()).getByRole('button', { name: 'Edit details' })
  expect(within(edit).getByText('Edit details')).toHaveClass('sr-only', '@md:not-sr-only')
  expect((await header()).firstElementChild).toHaveClass('@container')
})
