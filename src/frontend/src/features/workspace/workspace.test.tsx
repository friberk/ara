// Paper workspace (ARA-037). Replaces the legacy paper-page tests with the same behavioural coverage
// (metadata-only gate, provenance, dirty-only PATCH) plus the reader, mobile views and the evidence jump.
import { screen, waitFor, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

// jsdom has no canvas, so the lazy pdf.js viewer is replaced by a stand-in that shows what it was asked to render.
vi.mock('./PdfViewer', async () => {
  const { useEffect } = await import('react')
  return {
    default: function PdfViewerStub({ documentId, highlight, zoom, navigation, onDocumentLoad, onHighlight }: import('./PdfViewer').PdfViewerProps) {
      useEffect(() => onDocumentLoad(15), [onDocumentLoad])
      return (
        <div role="group" aria-label="PDF viewer">
          <p>{`Showing ${documentId}${highlight ? ` at page ${highlight.citation.page}` : ''}`}</p>
          {highlight?.claim && <p>{`Supporting “${highlight.claim}”`}</p>}
          <p>{`Zoom ${zoom}${navigation ? `, asked for page ${navigation.page}` : ''}`}</p>
          <button type="button" onClick={() => onHighlight('highlighted')}>Report passage found</button>
          <button type="button" onClick={() => onHighlight('page-only')}>Report passage not found</button>
        </div>
      )
    },
  }
})

const current: Citation = { chunk_id: 'chunk-2', document_id: 'doc-1', page: 2, excerpt: 'The measured answer accuracy is 86 percent.' }
const earlier: Citation = { chunk_id: 'chunk-0', document_id: 'doc-0', page: 1, excerpt: 'An earlier extraction of the abstract.' }

// The conversation module is built separately (ARA-036); this stand-in only exercises the workspace contract.
vi.mock('@/features/chat', async () => {
  const { useWorkspace } = await import('./workspace-context')
  return {
    ConversationPane: function ConversationStub() {
      const { showSource } = useWorkspace()
      return (
        <section aria-label="Conversation">
          <button type="button" onClick={() => showSource(current)}>Page 2</button>
          <button type="button" onClick={() => showSource(earlier)}>Page 1 of an earlier PDF</button>
          <button type="button" onClick={() => showSource(current, 'Accuracy reached 86 percent.')}>Page 2 for a claim</button>
        </section>
      )
    },
  }
})

const paper = {
  id: 'p1',
  title: 'Evidence based research',
  authors: ['A. Author', 'B. Writer'],
  year: 2024,
  abstract: 'We study how readers verify generated answers against their sources.',
  doi: '10.1234/evidence',
  sources: [{ provider: 'openalex', external_id: 'W1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, external_url: 'https://openalex.org/W1', pdf_url: null }],
  document_status: 'ready',
  active_document_id: 'doc-1',
  metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } },
}
const metadataOnly = { ...paper, document_status: 'metadata_only', active_document_id: null }

test('Given a metadata-only paper, Then the PDF gate and Details offer retrieval alongside manual attachment without posting', async () => {
  const { calls } = mockApi({ 'GET /papers/p1': metadataOnly, 'GET /papers/p1/fulltext': { paper_id: 'p1', availability: 'unknown', locations: [], attempts: [] } })
  const { user } = renderApp('/papers/p1')
  expect(await screen.findByRole('button', { name: 'Find PDF' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Upload PDF' })).toBeVisible()
  await user.click(screen.getByRole('tab', { name: 'Details' }))
  expect(within(screen.getByRole('tabpanel', { name: 'Details' })).getByRole('button', { name: 'Find PDF' })).toBeVisible()
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
})

function narrowScreen() {
  vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
    matches: query === '(max-width: 767px)', media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }))
}

// jsdom has no layout, so every element sits at (0, 0) and react-resizable-panels would treat each pointerdown
// as grabbing the split handle (it prevents the default, which stops Radix tabs from activating). Move the handle away.
const boundingRect = HTMLElement.prototype.getBoundingClientRect
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute('data-separator') ? new DOMRect(-500, -500, 1, 1) : boundingRect.call(this)
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

test('Given a ready paper, When the workspace opens, Then the header names it beside the PDF reader and the conversation', async () => {
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1')
  expect(await screen.findByRole('heading', { level: 1, name: paper.title })).toBeVisible()
  expect(screen.getByText('Ready to read')).toBeVisible()
  expect(screen.getByRole('region', { name: 'Conversation' })).toBeVisible()
  expect(await screen.findByText('Showing doc-1')).toBeVisible()
  expect(screen.getByRole('tab', { name: 'PDF', selected: true })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open original PDF' })).toHaveAttribute('href', '/api/v1/documents/doc-1/download')
  expect(screen.getByRole('textbox', { name: 'Page number' })).toHaveValue('1')
  expect(await screen.findByText('/ 15')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Hide reader' })).toBeVisible()
})

test('Given a metadata-only paper, Then the reader offers the PDF dropzone and keeps the abstract visible', async () => {
  mockApi({ 'GET /papers/p1': metadataOnly })
  renderApp('/papers/p1')
  expect(await screen.findByText('Attach the PDF to read, summarize and ask')).toBeVisible()
  const reader = screen.getByRole('tabpanel', { name: 'PDF' })
  expect(within(reader).getByLabelText('PDF file')).toBeInTheDocument()
  expect(within(reader).getByText(paper.abstract)).toBeVisible()
  expect(screen.queryByRole('link', { name: 'Open original PDF' })).not.toBeInTheDocument()
})

test('Given a metadata-only paper, When its PDF is uploaded in the reader, Then one stage list follows it until the PDF opens', async () => {
  let stored: object = metadataOnly
  let job = { id: 'job-1', kind: 'ingest', state: 'processing', stage: 'processing', progress: 20, error: null, result: null, attempts: 1, paper_id: 'p1', paper_title: paper.title }
  mockApi({
    'POST /documents': () => { stored = { ...metadataOnly, document_status: 'processing', active_document_id: 'doc-1' }; return json({ paper_id: 'p1', document_id: 'doc-1', job_id: 'job-1', duplicate: false }) },
    'GET /papers/p1': () => json(stored),
    'GET /jobs/job-1': () => json(job),
  })
  const { user } = renderApp('/papers/p1')
  const reader = await screen.findByRole('tabpanel', { name: 'PDF' })
  await user.upload(within(reader).getByLabelText('PDF file'), new File(['%PDF-1.7'], 'paper.pdf', { type: 'application/pdf' }))
  expect(await screen.findByText('Processing PDF')).toBeVisible()
  const steps = await within(reader).findByRole('list', { name: 'Preparation steps' })
  expect(within(steps).getByText('Uploaded')).toBeVisible()
  await waitFor(() => expect(within(steps).getByText('Reading pages').closest('li')).toHaveAttribute('aria-current', 'step'))
  expect(within(reader).getByRole('heading', { name: 'Preparing the PDF' })).toBeVisible()
  expect(within(reader).queryByText(/in the background/i)).not.toBeInTheDocument()
  stored = paper
  job = { ...job, state: 'completed', stage: 'completed', progress: 100 }
  expect(await within(reader).findByText('Showing doc-1', {}, { timeout: 4000 })).toBeVisible()
})

test('Given a PDF that arrived without an upload here, Then the processing view never claims it was uploaded', async () => {
  const job = { id: 'job-3', kind: 'ingest', state: 'processing', stage: 'extracting_metadata', progress: 50, error: null, result: null, attempts: 1, paper_id: 'p1', paper_title: null }
  mockApi({ 'GET /papers/p1': { ...metadataOnly, title: null, file_name: 'retrieved-paper.pdf', document_status: 'processing', active_document_id: 'doc-1' }, 'GET /jobs': { items: [job] }, 'GET /jobs/job-3': job })
  renderApp('/papers/p1')
  const reader = await screen.findByRole('tabpanel', { name: 'PDF' })
  const steps = await within(reader).findByRole('list', { name: 'Preparation steps' })
  await waitFor(() => expect(within(steps).getByText('Finding paper details').closest('li')).toHaveAttribute('aria-current', 'step'))
  expect(within(steps).queryByText(/Upload/)).not.toBeInTheDocument()
  expect(within(reader).queryByText(/uploaded/i)).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 1, name: 'retrieved-paper.pdf' })).toBeVisible()
})

test('Given a ready paper whose catalog lookup is running, When it finishes, Then the title updates without a reload', async () => {
  let stored = { ...paper, title: 'Printed title from the PDF', metadata_provenance: { title: { source: 'pdf' } } }
  let lookup = { id: 'lookup-1', kind: 'metadata', state: 'processing', stage: 'finding_metadata', progress: 50, error: null, result: null, attempts: 1, paper_id: 'p1', paper_title: stored.title, created_at: '2026-10-09T00:00:00Z' }
  mockApi({ 'GET /papers/p1': () => json(stored), 'GET /jobs': ({ url }) => json({ items: url.searchParams.get('kind') === 'metadata' ? [lookup] : [] }) })
  renderApp('/papers/p1')
  expect(await screen.findByRole('heading', { level: 1, name: 'Printed title from the PDF' })).toBeVisible()
  expect(await screen.findByText('Finding paper details')).toBeVisible()
  stored = { ...stored, title: 'Catalog title from OpenAlex', metadata_provenance: { title: { source: 'openalex' } } }
  lookup = { ...lookup, state: 'completed', stage: 'completed', progress: 100 }
  expect(await screen.findByRole('heading', { level: 1, name: 'Catalog title from OpenAlex' }, { timeout: 5000 })).toBeVisible()
  expect(screen.getByText('Ready to read')).toBeVisible()
})

test('Given field provenance, Then the details show the bibliography and where each field came from', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('tab', { name: 'Details' }))
  const details = screen.getByRole('tabpanel', { name: 'Details' })
  expect(within(details).getByText('A. Author, B. Writer')).toBeVisible()
  expect(within(details).getByRole('link', { name: '10.1234/evidence' })).toHaveAttribute('href', 'https://doi.org/10.1234/evidence')
  expect(within(details).getByRole('link', { name: 'OpenAlex' })).toHaveAttribute('href', 'https://openalex.org/W1')
  expect(within(details).getByRole('heading', { name: 'Metadata sources' })).toBeVisible()
  expect(within(details).getByText('Title: edited by you')).toBeVisible()
  expect(within(details).getByText('Authors: OpenAlex')).toBeVisible()
})

test('Given provider metadata, When only the title is edited, Then only the title is patched and the header follows', async () => {
  let stored = paper
  const { calls } = mockApi({
    'PATCH /papers/p1': ({ body }) => json(stored = { ...stored, ...(body as object), metadata_provenance: { ...stored.metadata_provenance, title: { source: 'manual' } } }),
    'GET /papers/p1': () => json(stored),
  })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('tab', { name: 'Details' }))
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  const title = screen.getByRole('textbox', { name: 'Title' })
  await user.clear(title)
  await user.type(title, 'Corrected title')
  await user.click(screen.getByRole('button', { name: 'Save bibliography' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Corrected title' })).toBeVisible()
  expect(calls.filter((call) => call.method === 'PATCH').map((call) => call.body)).toEqual([{ title: 'Corrected title' }])
  expect(screen.getByText('Authors: OpenAlex')).toBeVisible()
})

test('Given a ready paper, When a new PDF version is uploaded from Details, Then its stages stay there while the paper processes', async () => {
  let stored = paper
  const job = { id: 'job-2', kind: 'ingest', state: 'processing', stage: 'processing', progress: 10, error: null, result: null, attempts: 1, paper_id: 'p1', paper_title: paper.title }
  mockApi({
    'POST /documents': () => { stored = { ...paper, document_status: 'processing', active_document_id: 'doc-2' }; return json({ paper_id: 'p1', document_id: 'doc-2', job_id: 'job-2', duplicate: false }) },
    'GET /papers/p1': () => json(stored),
    'GET /jobs/job-2': job,
  })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('tab', { name: 'Details' }))
  const details = screen.getByRole('tabpanel', { name: 'Details' })
  await user.upload(within(details).getByLabelText('PDF file'), new File(['%PDF-1.7'], 'new-version.pdf', { type: 'application/pdf' }))
  expect(await screen.findByText('Processing PDF')).toBeVisible()
  const steps = await within(details).findByRole('list', { name: 'Preparation steps' })
  await waitFor(() => expect(within(steps).getByText('Reading pages').closest('li')).toHaveAttribute('aria-current', 'step'))
  expect(within(details).queryByText(/in the background/i)).not.toBeInTheDocument()
})

test('Given a narrow screen, Then Chat, PDF and Details are tabs that follow ?view=', async () => {
  narrowScreen()
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1?view=details')
  expect(await screen.findByRole('tab', { name: 'Details', selected: true })).toBeVisible()
  expect(screen.getByText('Title: edited by you')).toBeVisible()
  expect(screen.queryByRole('separator')).not.toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: 'Chat' }))
  expect(screen.getByRole('tab', { name: 'Chat', selected: true })).toBeVisible()
  expect(screen.getByRole('region', { name: 'Conversation' })).toBeVisible()
  await user.click(screen.getByRole('tab', { name: 'PDF' }))
  expect(await screen.findByText('Showing doc-1')).toBeVisible()
})

test('Given a narrow screen, When a citation asks for its source, Then the PDF tab opens at the cited page', async () => {
  narrowScreen()
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  expect(await screen.findByRole('tab', { name: 'Chat', selected: true })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Page 2' }))
  expect(screen.getByRole('tab', { name: 'PDF', selected: true })).toBeVisible()
  expect(await screen.findByText('Showing doc-1 at page 2')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Report passage not found' }))
  expect(screen.getByText('Couldn’t pinpoint the passage, so showing page 2.')).toBeVisible()
  // Assistive technology hears one polite announcement that names the page and says nothing was highlighted.
  expect(screen.getByText('Showing page 2. The cited passage could not be highlighted.')).toHaveAttribute('role', 'status')
})

test('Given the Details tab is open, When a citation asks for its source, Then the reader returns to the PDF', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('tab', { name: 'Details' }))
  await user.click(screen.getByRole('button', { name: 'Page 2' }))
  expect(screen.getByRole('tab', { name: 'PDF', selected: true })).toBeVisible()
  expect(await screen.findByText('Showing doc-1 at page 2')).toBeVisible()
})

test('Given a citation, When the reader marks its passage, Then the outcome is announced politely', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('button', { name: 'Page 2' }))
  await user.click(await screen.findByRole('button', { name: 'Report passage found' }))
  expect(screen.getByText('Highlighted the cited passage on page 2.')).toHaveAttribute('role', 'status')
  expect(screen.queryByText('Couldn’t pinpoint the passage, so showing page 2.')).not.toBeInTheDocument()
})

test('Given a chip that names its claim, When it asks for its source, Then the reader receives the claim with the citation', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('button', { name: 'Page 2 for a claim' }))
  expect(await screen.findByText('Showing doc-1 at page 2')).toBeVisible()
  expect(screen.getByText('Supporting “Accuracy reached 86 percent.”')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Page 2' }))
  expect(screen.queryByText(/^Supporting/)).not.toBeInTheDocument()
})

test('Given a citation from an earlier PDF, When its source is shown, Then the reader opens that version and says so', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('button', { name: 'Page 1 of an earlier PDF' }))
  expect(await screen.findByText('Showing an earlier PDF version')).toBeVisible()
  expect(await screen.findByText('Showing doc-0 at page 1')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open original PDF' })).toHaveAttribute('href', '/api/v1/documents/doc-0/download')
  await user.click(screen.getByRole('button', { name: 'Back to current PDF' }))
  expect(await screen.findByText('Showing doc-1')).toBeVisible()
  expect(screen.queryByText('Showing an earlier PDF version')).not.toBeInTheDocument()
})

test('Given a processing paper, Then the reader follows its ingest job', async () => {
  const job = { id: 'job-1', kind: 'ingest', state: 'processing', stage: 'extracting_metadata', progress: 40, error: null, result: null, attempts: 1, paper_id: 'p1', paper_title: paper.title }
  const { calls } = mockApi({ 'GET /papers/p1': { ...paper, document_status: 'processing' }, 'GET /jobs': { items: [job] }, 'GET /jobs/job-1': job })
  renderApp('/papers/p1')
  const steps = await screen.findByRole('list', { name: 'Preparation steps' })
  await waitFor(() => expect(within(steps).getByText('Finding paper details').closest('li')).toHaveAttribute('aria-current', 'step'))
  expect(within(steps).getByText('Reading pages').closest('li')).toHaveTextContent('Done')
  const jobsQuery = calls.find((call) => call.path === '/jobs' && call.url.searchParams.get('kind') === 'ingest')?.url.searchParams
  expect(Object.fromEntries(jobsQuery ?? [])).toEqual({ paper_id: 'p1', kind: 'ingest', active: 'true' })
})

test('Given job filtering is unavailable, When a paper is processing, Then a generic processing state is shown', async () => {
  mockApi({ 'GET /papers/p1': { ...paper, document_status: 'processing' }, 'GET /jobs': () => json({ code: 'NOT_FOUND', message: 'Not found.' }, 404) })
  renderApp('/papers/p1')
  expect(await screen.findByRole('heading', { name: 'Preparing the PDF' })).toBeVisible()
  expect(within(screen.getByRole('list', { name: 'Preparation steps' })).getByText('Reading pages').closest('li')).toHaveAttribute('aria-current', 'step')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('Given a failed paper, When its ingest job is known, Then the reader explains and offers a retry', async () => {
  const failed = { id: 'job-9', kind: 'ingest', state: 'failed', stage: 'failed', progress: 30, error: { code: 'OCR_REQUIRED', message: 'No readable text found. Upload a text PDF; OCR is disabled.' }, result: null, attempts: 3, paper_id: 'p1', paper_title: paper.title }
  const { calls } = mockApi({ 'GET /papers/p1': { ...paper, document_status: 'failed' }, 'GET /jobs': { items: [failed] }, 'POST /jobs/job-9/retry': { ...failed, state: 'queued' } })
  const { user } = renderApp('/papers/p1')
  expect(await screen.findByText('No readable text found. Upload a text PDF; OCR is disabled.')).toBeVisible()
  expect(screen.getByLabelText('PDF file')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Retry processing' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/jobs/job-9/retry')).toBe(true))
})

test('Given an unknown paper, Then the workspace says so and links back to the library', async () => {
  mockApi({ 'GET /papers/p1': () => json({ code: 'PAPER_NOT_FOUND', message: 'Paper not found.' }, 404) })
  renderApp('/papers/p1')
  expect(await screen.findByRole('heading', { name: 'Paper not found' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open library' })).toHaveAttribute('href', '/library')
})

// TEST-AFTER coverage: these behaviours were implemented before any test named them. Each case was added after the
// code, passed at once, and was then mutation-verified (it fails when the behaviour it names is removed).
describe('test-after coverage (mutation-verified)', () => {
  test('Given a loaded PDF, When the toolbar pages and zooms, Then the viewer is asked for that page and size', async () => {
    mockApi({ 'GET /papers/p1': paper })
    const { user } = renderApp('/papers/p1')
    expect(await screen.findByText('Zoom 1')).toBeVisible()
    const field = await screen.findByRole('textbox', { name: 'Page number' })
    await waitFor(() => expect(field).toBeEnabled())
    await user.clear(field)
    await user.type(field, '99{Enter}')
    expect(screen.getByText('Zoom 1, asked for page 15')).toBeVisible()
    expect(field).toHaveValue('15')
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(screen.getByText('Zoom 1, asked for page 14')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByText('Zoom 1.1, asked for page 14')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Fit width' }))
    for (let step = 0; step < 4; step += 1) await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByText('Zoom 0.5, asked for page 14')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled()
  })

  test('Given a metadata-only paper, When Details offers to attach a PDF, Then the reader returns to the PDF dropzone', async () => {
    mockApi({ 'GET /papers/p1': metadataOnly })
    const { user } = renderApp('/papers/p1')
    await user.click(await screen.findByRole('tab', { name: 'Details' }))
    await user.click(screen.getByRole('button', { name: 'Attach a PDF' }))
    expect(screen.getByRole('tab', { name: 'PDF', selected: true })).toBeVisible()
    expect(within(screen.getByRole('tabpanel', { name: 'PDF' })).getByText('Attach the PDF to read, summarize and ask')).toBeVisible()
  })

  test('Given a narrow screen, When Details offers to attach a PDF, Then the PDF view opens', async () => {
    narrowScreen()
    mockApi({ 'GET /papers/p1': metadataOnly })
    const { user } = renderApp('/papers/p1?view=details')
    await user.click(await screen.findByRole('button', { name: 'Attach a PDF' }))
    expect(screen.getByRole('tab', { name: 'PDF', selected: true })).toBeVisible()
  })

  test('Given an impossible publication year, When the bibliography is saved, Then the field explains the range and nothing is sent', async () => {
    const { calls } = mockApi({ 'GET /papers/p1': paper })
    const { user } = renderApp('/papers/p1')
    await user.click(await screen.findByRole('tab', { name: 'Details' }))
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const year = screen.getByRole('textbox', { name: 'Publication year' })
    await user.clear(year)
    await user.type(year, '12')
    await user.click(screen.getByRole('button', { name: 'Save bibliography' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a publication year between 1500 and 2100.')
    expect(year).toHaveAttribute('aria-invalid', 'true')
    expect(calls.some((call) => call.method === 'PATCH')).toBe(false)
  })

  test('Given the paper cannot be loaded, Then the error is shown inline with a retry', async () => {
    let attempts = 0
    mockApi({ 'GET /papers/p1': () => (attempts += 1) === 1 ? json({ code: 'UNAVAILABLE', message: 'The library is temporarily unavailable.' }, 503) : json(paper) })
    const { user } = renderApp('/papers/p1')
    expect(await screen.findByRole('alert')).toHaveTextContent('The library is temporarily unavailable.')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { level: 1, name: paper.title })).toBeVisible()
  })
})
