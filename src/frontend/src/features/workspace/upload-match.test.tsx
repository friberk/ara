// Uploads that are papers already in the library (ARA-086): attach, replace or cancel, and the PDF-on-its-way copy.
import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

vi.mock('./PdfViewer', () => ({ default: ({ documentId }: { documentId: string }) => <p>{`Showing ${documentId}`}</p> }))
// jsdom has no layout, so the split handle would swallow clicks; move it away, as workspace.test does.
const boundingRect = HTMLElement.prototype.getBoundingClientRect
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute('data-separator') ? new DOMRect(-500, -500, 1, 1) : boundingRect.call(this)
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
// The first test of the file loads the lazy workspace route, which can take seconds on a busy machine.
const firstLoad = { timeout: 10_000 }

const library = { id: 'p-lib', title: 'Exploiting input sanitization for regex denial of service', authors: ['Efe Barlas'], year: 2022, abstract: null, doi: '10.1145/3510003.3510047', sources: [], document_status: 'ready', active_document_id: 'd-old', metadata_provenance: {}, file_name: 'old.pdf', upload_match: null, pdf_doi_owner: null }
const pending = { id: 'p-new', title: null, authors: [], year: null, abstract: null, doi: null, sources: [], document_status: 'processing', active_document_id: 'd-new', metadata_provenance: {}, file_name: 'sec18.pdf', pdf_doi_owner: null, upload_match: { paper_id: 'p-lib', title: library.title, has_pdf: true, matched_by: 'doi', found_by: 'ingest' } }

test('Given an upload that matches a library paper with a PDF, Then the reader asks to replace it and Replace opens that paper', async () => {
  const { calls } = mockApi({ 'GET /papers/p-new': pending, 'GET /papers/p-lib': { ...library, active_document_id: 'd-new', document_status: 'processing' }, 'POST /uploads/p-new/match': () => json({ ...library, active_document_id: 'd-new', document_status: 'processing' }) })
  const { user } = renderApp('/papers/p-new')
  const reader = await screen.findByRole('region', { name: 'PDF reader' }, firstLoad)
  expect(await within(reader).findByText(`This PDF matches “${library.title}” in your library.`)).toBeVisible()
  expect(within(reader).getByText('It already has a PDF. Replace it with this one?')).toBeVisible()
  expect(within(reader).queryByRole('heading', { name: 'Preparing the PDF' })).not.toBeInTheDocument()
  expect(screen.getByText('Matches a library paper')).toBeVisible()
  await user.click(within(reader).getByRole('button', { name: 'Replace PDF' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/uploads/p-new/match')?.body).toEqual({ decision: 'attach' }))
  expect(await screen.findByRole('heading', { level: 1, name: library.title })).toBeVisible()
  expect(await screen.findByText(`The PDF replaced the one on “${library.title}”.`)).toBeVisible()
})

test('Given the same decision, When Cancel is pressed, Then the upload is discarded and the library opens', async () => {
  const { calls } = mockApi({ 'GET /papers/p-new': pending, 'POST /uploads/p-new/match': () => new Response(null, { status: 204 }) })
  const { user } = renderApp('/papers/p-new')
  await user.click(await screen.findByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ decision: 'discard' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  expect(await screen.findByText('Upload discarded.')).toBeVisible()
})

test('Given a readable upload the catalog later matched to a paper without a PDF, Then a banner offers to attach it', async () => {
  const late = { ...pending, title: 'Exploiting Input Sanitization', document_status: 'ready', upload_match: { ...pending.upload_match, has_pdf: false, found_by: 'lookup', matched_by: 'title' } }
  const { calls } = mockApi({ 'GET /papers/p-new': late, 'GET /papers/p-lib': library, 'POST /uploads/p-new/match': () => json(library) })
  const { user } = renderApp('/papers/p-new')
  const banner = await screen.findByRole('region', { name: 'Library match' })
  expect(within(banner).getByText('It has no PDF yet. Attach this one to it?')).toBeVisible()
  await user.click(within(banner).getByRole('button', { name: 'Attach PDF' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/uploads/p-new/match')).toBe(true))
  expect(await screen.findByText(`The PDF was attached to “${library.title}”.`)).toBeVisible()
})

test('Given an upload that ingestion attached to a library paper, When its old link opens, Then the library paper opens with a note', async () => {
  mockApi({ 'GET /papers/p-new': library, 'GET /papers/p-lib': library })
  renderApp('/papers/p-new')
  expect(await screen.findByRole('heading', { level: 1, name: library.title })).toBeVisible()
  expect(await screen.findByText(`This PDF matched “${library.title}” in your library, so it was added there.`)).toBeVisible()
})

const saved = { ...library, id: 'p2', title: 'Saved paper', document_status: 'metadata_only', active_document_id: null, doi: '10.5555/saved' }
const retrieving = { paper_id: 'p2', availability: 'open_copy_reported', locations: [], retrieval_job: { id: 'r1', kind: 'fulltext', state: 'processing', stage: 'fetching_pdf', progress: 40, result: null }, document_id: null, ingest_job_id: null, attempts: [], source_host: 'arxiv.org' }

test('Given a PDF being retrieved automatically, Then the header icon, the composer and the upload option all say it is on its way', async () => {
  mockApi({ 'GET /papers/p2': saved, 'GET /papers/p2/fulltext': retrieving })
  renderApp('/papers/p2')
  expect(await screen.findByRole('img', { name: 'Preparing PDF…' })).toBeVisible()
  expect(screen.queryByRole('img', { name: 'No PDF yet' })).not.toBeInTheDocument()
  expect(await screen.findByText('You can ask questions once the PDF is ready.')).toBeVisible()
  const reader = screen.getByRole('region', { name: 'PDF reader' })
  expect(within(reader).queryByText('Attach the PDF to read, summarize and ask')).not.toBeInTheDocument()
  expect(within(reader).getByRole('button', { name: 'Upload your own copy instead' })).toBeVisible()
  expect(within(reader).getByLabelText('PDF file')).toBeInTheDocument()
})

test('Given no retrieval running, Then upload stays the primary way to add the PDF', async () => {
  mockApi({ 'GET /papers/p2': saved, 'GET /papers/p2/fulltext': { ...retrieving, retrieval_job: { ...retrieving.retrieval_job, state: 'failed', result: { outcome: 'not_found' } } } })
  renderApp('/papers/p2')
  const reader = await screen.findByRole('region', { name: 'PDF reader' })
  expect(await within(reader).findByText('Attach the PDF to read, summarize and ask')).toBeVisible()
  expect(screen.getByRole('img', { name: 'No PDF yet' })).toBeVisible()
  expect(await screen.findByText('Attach a PDF to ask questions about this paper.')).toBeVisible()
})
