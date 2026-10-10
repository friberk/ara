// Paper workspace (ARA-037, ARA-097): the reader without tabs, the conversation, the Chat | PDF segments on narrow
// screens and the evidence jump. The paper's details live behind ⓘ (paper-details.test.tsx); the PDF menu has its own file.
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
          <button type="button" onClick={() => onHighlight('region')}>Report region outlined</button>
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

test('Given a metadata-only paper and no OpenAlex key, Then the reader offers the DOI link beside the upload without asking for retrieval', async () => {
  const { calls } = mockApi({ 'GET /papers/p1': metadataOnly, 'GET /papers/p1/fulltext': { paper_id: 'p1', api_key_configured: false, retrieval_job: null } })
  renderApp('/papers/p1')
  const reader = await screen.findByRole('region', { name: 'PDF reader' })
  expect(await within(reader).findByRole('link', { name: 'Open the paper' })).toHaveAttribute('href', 'https://doi.org/10.1234/evidence')
  expect(within(reader).getByRole('button', { name: 'Upload PDF' })).toBeVisible()
  // ARA-087: without a key nothing can be downloaded, so nothing is requested.
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

test('Given a ready paper, When the workspace opens, Then the reader shows its PDF beside the conversation, with no tabs', async () => {
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1')
  expect(await screen.findByRole('heading', { level: 1, name: paper.title })).toBeVisible()
  expect(screen.queryByRole('img', { name: /PDF/ })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Conversation' })).toBeVisible()
  const reader = screen.getByRole('region', { name: 'PDF reader' })
  expect(await within(reader).findByText('Showing doc-1')).toBeVisible()
  expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Details' })).not.toBeInTheDocument()
  expect(within(reader).getByRole('button', { name: 'PDF options' })).toBeVisible()
  expect(screen.getByRole('textbox', { name: 'Page number' })).toHaveValue('1')
  expect(await screen.findByText('/ 15')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Hide reader' })).toBeVisible()
})

test('Given a metadata-only paper, Then the reader offers the PDF dropzone and keeps the abstract visible', async () => {
  mockApi({ 'GET /papers/p1': metadataOnly })
  renderApp('/papers/p1')
  expect(await screen.findByText('Attach the PDF to read, summarize and ask')).toBeVisible()
  const reader = screen.getByRole('region', { name: 'PDF reader' })
  expect(within(reader).getByLabelText('PDF file')).toBeInTheDocument()
  expect(within(reader).getByText(paper.abstract)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'PDF options' })).not.toBeInTheDocument()
  expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
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
  const reader = await screen.findByRole('region', { name: 'PDF reader' })
  await user.upload(within(reader).getByLabelText('PDF file'), new File(['%PDF-1.7'], 'paper.pdf', { type: 'application/pdf' }))
  expect(await screen.findByRole('img', { name: 'Preparing PDF…' })).toBeVisible()
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
  const reader = await screen.findByRole('region', { name: 'PDF reader' })
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
  // The PDF is readable meanwhile, so the status says so and the lookup is a quiet note beside it.
  expect(await screen.findByText('Finding paper details')).toBeVisible()
  expect(screen.queryByRole('img', { name: /PDF/ })).not.toBeInTheDocument()
  stored = { ...stored, title: 'Catalog title from OpenAlex', metadata_provenance: { title: { source: 'openalex' } } }
  lookup = { ...lookup, state: 'completed', stage: 'completed', progress: 100 }
  expect(await screen.findByRole('heading', { level: 1, name: 'Catalog title from OpenAlex' }, { timeout: 5000 })).toBeVisible()
  expect(screen.queryByRole('img', { name: /PDF/ })).not.toBeInTheDocument()
})

test('Given provider metadata, When only the title is edited, Then only the title is patched and the header follows', async () => {
  let stored = paper
  const { calls } = mockApi({
    'PATCH /papers/p1': ({ body }) => json(stored = { ...stored, ...(body as object), metadata_provenance: { ...stored.metadata_provenance, title: { source: 'manual' } } }),
    'GET /papers/p1': () => json(stored),
  })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('button', { name: 'Paper details' }))
  await user.click(within(await screen.findByRole('dialog', { name: paper.title })).getByRole('button', { name: 'Edit details' }))
  const title = within(await screen.findByRole('dialog', { name: 'Edit details' })).getByRole('textbox', { name: 'Title' })
  await user.clear(title)
  await user.type(title, 'Corrected title')
  await user.click(screen.getByRole('button', { name: 'Save details' }))
  // The sheet names the paper too; behind it, the header follows once the sheet closes.
  expect(await screen.findByRole('dialog', { name: 'Corrected title' })).toBeVisible()
  await user.keyboard('{Escape}')
  expect(await screen.findByRole('heading', { level: 1, name: 'Corrected title' })).toBeVisible()
  expect(calls.filter((call) => call.method === 'PATCH').map((call) => call.body)).toEqual([{ title: 'Corrected title' }])
})

test('Given a narrow screen, Then Chat and PDF are the only segments, and they follow ?view=', async () => {
  narrowScreen()
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1?view=pdf')
  expect(await screen.findByRole('tab', { name: 'PDF', selected: true })).toBeVisible()
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Chat', 'PDF'])
  expect(await screen.findByText('Showing doc-1')).toBeVisible()
  expect(screen.queryByRole('separator')).not.toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: 'Chat' }))
  expect(screen.getByRole('tab', { name: 'Chat', selected: true })).toBeVisible()
  expect(screen.getByRole('region', { name: 'Conversation' })).toBeVisible()
  await user.click(screen.getByRole('tab', { name: 'PDF' }))
  expect(await screen.findByText('Showing doc-1')).toBeVisible()
})

test('Given a narrow screen and an old ?view=details link, Then the conversation opens', async () => {
  narrowScreen()
  mockApi({ 'GET /papers/p1': paper })
  renderApp('/papers/p1?view=details')
  expect(await screen.findByRole('tab', { name: 'Chat', selected: true })).toBeVisible()
  expect(screen.getByRole('region', { name: 'Conversation' })).toBeVisible()
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

test('Given a citation, When the reader marks its passage, Then the outcome is announced politely', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('button', { name: 'Page 2' }))
  await user.click(await screen.findByRole('button', { name: 'Report passage found' }))
  expect(screen.getByText('Highlighted the cited passage on page 2.')).toHaveAttribute('role', 'status')
  expect(screen.queryByText('Couldn’t pinpoint the passage, so showing page 2.')).not.toBeInTheDocument()
})

test('Given the reader outlines the stored region instead of the text, Then it says so and does not claim a highlight', async () => {
  mockApi({ 'GET /papers/p1': paper })
  const { user } = renderApp('/papers/p1')
  await user.click(await screen.findByRole('button', { name: 'Page 2' }))
  await user.click(await screen.findByRole('button', { name: 'Report region outlined' }))
  expect(screen.getByText('Outlined the cited region on page 2.')).toHaveAttribute('role', 'status')
  expect(screen.getByText('Couldn’t find the exact text, so outlined the cited region on page 2.')).toBeInTheDocument()
  expect(screen.queryByText('Highlighted the cited passage on page 2.')).not.toBeInTheDocument()
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

test('Given an unknown or deleted paper, Then the workspace returns to the Library with a short note', async () => {
  mockApi({ 'GET /papers/p1': () => json({ code: 'PAPER_NOT_FOUND', message: 'Paper not found.' }, 404) })
  renderApp('/papers/p1/chats/c1')
  expect(await screen.findByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  expect(screen.getByText('That paper isn’t in your library anymore. It may have been deleted.')).toBeVisible()
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

  test('Given an impossible publication year, When the details are saved, Then the field explains the range and nothing is sent', async () => {
    const { calls } = mockApi({ 'GET /papers/p1': paper })
    const { user } = renderApp('/papers/p1')
    await user.click(await screen.findByRole('button', { name: 'Paper details' }))
    await user.click(within(await screen.findByRole('dialog', { name: paper.title })).getByRole('button', { name: 'Edit details' }))
    const year = within(await screen.findByRole('dialog', { name: 'Edit details' })).getByRole('textbox', { name: 'Publication year' })
    await user.clear(year)
    await user.type(year, '12')
    await user.click(screen.getByRole('button', { name: 'Save details' }))
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
