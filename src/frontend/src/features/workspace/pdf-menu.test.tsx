// The reader's PDF menu (ARA-097): what the file is, and opening, downloading, replacing or removing it.
import { screen, waitFor, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

vi.mock('./PdfViewer', async () => {
  const { useEffect } = await import('react')
  return {
    default: function PdfViewerStub({ documentId, onDocumentLoad }: import('./PdfViewer').PdfViewerProps) {
      useEffect(() => onDocumentLoad(15), [onDocumentLoad])
      return <p>{`Showing ${documentId}`}</p>
    },
  }
})

const earlier: Citation = { chunk_id: 'chunk-0', document_id: 'doc-0', page: 1, excerpt: 'An earlier extraction of the abstract.' }
vi.mock('@/features/chat', async () => {
  const { useWorkspace } = await import('./workspace-context')
  return {
    ConversationPane: function ConversationStub() {
      const { showSource } = useWorkspace()
      return <section aria-label="Conversation"><button type="button" onClick={() => showSource(earlier)}>Page 1 of an earlier PDF</button></section>
    },
  }
})

const paper = {
  id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: 'We study verification.', doi: '10.1234/evidence', sources: [],
  document_status: 'ready', active_document_id: 'doc-1', file_name: 'evidence.pdf', metadata_provenance: {},
}
const removed = { ...paper, document_status: 'metadata_only', active_document_id: null, file_name: null }
const document = { id: 'doc-1', paper_id: 'p1', file_name: 'evidence.pdf', page_count: 15, byte_size: 1_468_006, status: 'ready', acquisition: null }
const preview = { pdfs: 1, summaries: 2, chats: [{ id: 'c1', title: 'Accuracy question' }], active_jobs: 0, answering: false }

const boundingRect = HTMLElement.prototype.getBoundingClientRect
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute('data-separator') ? new DOMRect(-500, -500, 1, 1) : boundingRect.call(this)
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

async function openMenu(user: ReturnType<typeof renderApp>['user']) {
  await screen.findByText('Showing doc-1')
  await user.click(screen.getByRole('button', { name: 'PDF options' }))
  return screen.findByRole('menu')
}

test('Given an uploaded PDF, When the PDF menu opens, Then its header names the file, pages, size and source, above Open, Download, Replace and Remove', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /documents/doc-1': document })
  const { user } = renderApp('/papers/p1')
  const menu = await openMenu(user)
  expect(await within(menu).findByText('evidence.pdf')).toBeVisible()
  expect(within(menu).getByText('15 pages · 1.4 MB')).toBeVisible()
  expect(within(menu).getByText('Uploaded')).toBeVisible()
  // The header is a label, not something to choose.
  expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Open original', 'Download', 'Replace PDF…', 'Remove PDF…'])
  const open = within(menu).getByRole('menuitem', { name: 'Open original' })
  expect(open).toHaveAttribute('href', '/api/v1/documents/doc-1/download')
  expect(open).toHaveAttribute('target', '_blank')
  expect(within(menu).getByRole('menuitem', { name: 'Download' })).toHaveAttribute('download', 'evidence.pdf')
  expect(within(menu).getByRole('menuitem', { name: 'Remove PDF…' })).toHaveAttribute('data-variant', 'destructive')
})

test('Given a PDF downloaded from OpenAlex, Then the menu says where it came from', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /documents/doc-1': { ...document, acquisition: { method: 'provider_download', provider: 'openalex' } } })
  const { user } = renderApp('/papers/p1')
  const menu = await openMenu(user)
  expect(await within(menu).findByText('Downloaded from OpenAlex')).toBeVisible()
})

test('Given Remove PDF…, When confirmed, Then the dialog says what happens, the PDF is removed and the reader returns to upload', async () => {
  let stored: object = paper
  const { calls } = mockApi({
    'GET /papers/p1': () => json(stored),
    'GET /documents/doc-1': document,
    'GET /papers/p1/pdf/removal-preview': preview,
    'DELETE /papers/p1/pdf': () => { stored = removed; return new Response(null, { status: 204 }) },
  })
  const { user } = renderApp('/papers/p1')
  const menu = await openMenu(user)
  await user.click(within(menu).getByRole('menuitem', { name: 'Remove PDF…' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Remove this PDF?' })
  expect(within(dialog).getByText('“evidence.pdf” is deleted. This can’t be undone.')).toBeVisible()
  const effects = await within(dialog).findByRole('list', { name: 'What happens' })
  expect(within(effects).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    'The reader goes back to uploading a PDF.',
    '2 summaries of this PDF are deleted.',
    'Earlier answers keep their quoted passages, but their page links won’t open.',
    '1 conversation that used it stays readable but can’t take new questions.',
  ])
  expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
  await user.click(within(dialog).getByRole('button', { name: 'Remove PDF' }))
  expect(await screen.findByText('Attach the PDF to read, summarize and ask')).toBeVisible()
  expect(screen.getByText('PDF removed')).toBeVisible()
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual(['/papers/p1/pdf'])
})

test('Given a conversation still writing an answer, Then Remove PDF waits for it', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /documents/doc-1': document, 'GET /papers/p1/pdf/removal-preview': { ...preview, answering: true } })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await openMenu(user)).getByRole('menuitem', { name: 'Remove PDF…' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Remove this PDF?' })
  expect(await within(dialog).findByText('A conversation that uses this PDF is still writing an answer. Remove the PDF when it finishes.')).toBeVisible()
  expect(within(dialog).getByRole('button', { name: 'Remove PDF' })).toBeDisabled()
})

test('Given earlier versions, When the removal fails, Then the dialog lists them and shows the error where it happened', async () => {
  mockApi({
    'GET /papers/p1': paper,
    'GET /documents/doc-1': document,
    'GET /papers/p1/pdf/removal-preview': { ...preview, pdfs: 3, summaries: 1, chats: [], active_jobs: 1 },
    'DELETE /papers/p1/pdf': () => json({ code: 'CHAT_BUSY', message: 'Wait for the current answer to finish before removing the PDF.' }, 409),
  })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await openMenu(user)).getByRole('menuitem', { name: 'Remove PDF…' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Remove this PDF?' })
  const effects = await within(dialog).findByRole('list', { name: 'What happens' })
  expect(within(effects).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    'The reader goes back to uploading a PDF.',
    '2 earlier versions of the PDF are deleted too.',
    '1 summary of this PDF is deleted.',
    '1 background task for this PDF stops.',
  ])
  await user.click(within(dialog).getByRole('button', { name: 'Remove PDF' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Wait for the current answer to finish before removing the PDF.')
})

test('Given Replace PDF…, When a new PDF is uploaded, Then it becomes the active PDF and the reader follows its preparation', async () => {
  let stored: object = paper
  const job = { id: 'job-2', kind: 'ingest', state: 'processing', stage: 'processing', progress: 10, error: null, result: null, attempts: 1, paper_id: 'p1', paper_title: paper.title }
  const { calls } = mockApi({
    'GET /papers/p1': () => json(stored),
    'GET /documents/doc-1': document,
    'POST /documents': () => { stored = { ...paper, document_status: 'processing', active_document_id: 'doc-2' }; return json({ paper_id: 'p1', document_id: 'doc-2', job_id: 'job-2', duplicate: false }) },
    'GET /jobs/job-2': job,
  })
  const { user } = renderApp('/papers/p1')
  await user.click(within(await openMenu(user)).getByRole('menuitem', { name: 'Replace PDF…' }))
  const dialog = await screen.findByRole('dialog', { name: 'Replace the PDF' })
  expect(within(dialog).getByText('The new PDF becomes the one you read and ask about. Earlier answers keep citing the PDF they used.')).toBeVisible()
  await user.upload(within(dialog).getByLabelText('PDF file'), new File(['%PDF-1.7'], 'new-version.pdf', { type: 'application/pdf' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Replace the PDF' })).not.toBeInTheDocument())
  const reader = screen.getByRole('region', { name: 'PDF reader' })
  const steps = await within(reader).findByRole('list', { name: 'Preparation steps' })
  // The reader follows the new upload's own job, so its first step is the upload.
  expect(await within(steps).findByText('Uploaded')).toBeVisible()
  await waitFor(() => expect(within(steps).getByText('Reading pages').closest('li')).toHaveAttribute('aria-current', 'step'))
  const upload = calls.find((call) => call.method === 'POST' && call.path === '/documents')!.body as FormData
  expect(upload.get('paper_id')).toBe('p1')
})

test('Given an earlier PDF version a citation opened, Then its menu only opens or downloads that version', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /documents/doc-1': document, 'GET /documents/doc-0': { ...document, id: 'doc-0', file_name: 'first-draft.pdf', page_count: 9 } })
  const { user } = renderApp('/papers/p1')
  await screen.findByText('Showing doc-1')
  await user.click(screen.getByRole('button', { name: 'Page 1 of an earlier PDF' }))
  expect(await screen.findByText('Showing an earlier PDF version')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'PDF options' }))
  const menu = await screen.findByRole('menu')
  expect(await within(menu).findByText('first-draft.pdf')).toBeVisible()
  expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Open original', 'Download'])
  expect(within(menu).getByRole('menuitem', { name: 'Open original' })).toHaveAttribute('href', '/api/v1/documents/doc-0/download')
})
