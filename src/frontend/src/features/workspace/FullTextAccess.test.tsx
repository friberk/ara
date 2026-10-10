import { screen, waitFor } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { FullTextAccess } from './FullTextAccess'
import { UploadDropzone } from '@/components/upload/UploadDropzone'

// PDFs come only from OpenAlex's stored copies; otherwise the DOI link and an upload (ARA-087).
const openalex = { provider: 'openalex' as const, external_id: 'W123', title: 'Research', authors: [], year: null, abstract: null, doi: '10.5555/paper', external_url: 'https://publisher.example/paper', pdf_url: 'https://publisher.example/paper.pdf' }
const paper: Paper = { id: 'p1', title: 'Research', authors: [], year: null, abstract: null, doi: openalex.doi, document_status: 'metadata_only', active_document_id: null, sources: [openalex], metadata_provenance: {} }
const idle = { paper_id: 'p1', api_key_configured: true, retrieval_job: null, document_id: null, ingest_job_id: null }
const job = { id: 'j1', kind: 'fulltext', state: 'processing', stage: 'discovering_fulltext', progress: 10, result: null, error: null, updated_at: new Date().toISOString() }
const failed = (outcome: string, extra: Record<string, unknown> = {}) => ({ ...idle, retrieval_job: { ...job, state: 'failed', stage: 'failed', result: { outcome, retry_after: null }, ...extra } })
const doi = 'https://doi.org/10.5555/paper'
afterEach(() => vi.unstubAllGlobals())

test('Given a saved paper with no attempt yet, When its workspace opens, Then retrieval from OpenAlex starts once by itself', async () => {
  let started = false
  const { calls } = mockApi({
    'GET /papers/p1/fulltext': () => Response.json({ ...idle, retrieval_job: started ? { ...job, state: 'queued', stage: 'queued' } : null }),
    'POST /papers/p1/retrieve-fulltext/automatic': () => { started = true; return Response.json({ paper_id: 'p1', job_id: 'j1' }) },
  })
  // The reader and the Details tab both show retrieval; together they still ask once.
  renderWithProviders(<><FullTextAccess paper={paper} /><FullTextAccess paper={paper} /></>)
  expect((await screen.findAllByText('Checking OpenAlex for a stored PDF'))[0]).toBeVisible()
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1))
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.queryByText(/background/i)).not.toBeInTheDocument()
})

test('Given a download in progress, Then the progress says it comes from OpenAlex', async () => {
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, stage: 'fetching_pdf', progress: 40 } } })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByRole('status')).toHaveTextContent('Downloading the PDF from OpenAlex')
})

test('Given no OpenAlex API key, Then nothing is requested and the DOI link, upload request and key note show', async () => {
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { ...idle, api_key_configured: false } })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByRole('link', { name: 'Open the paper' })).toHaveAttribute('href', doi)
  expect(screen.getByText(/download the PDF and upload it here/)).toBeVisible()
  expect(screen.getByText(/OpenAlex API key/)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
})

test('Given OpenAlex has no stored copy, Then the DOI link and an upload request replace any retry or browser PDF link', async () => {
  mockApi({ 'GET /papers/p1/fulltext': failed('not_stored') })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByText('OpenAlex doesn’t have this PDF')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open the paper' })).toHaveAttribute('href', doi)
  expect(screen.getByText(/download the PDF and upload it here/)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Open PDF in browser|Open publisher|Semantic Scholar/ })).not.toBeInTheDocument()
  expect(screen.queryByText(/VPN|university/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/OpenAlex API key/)).not.toBeInTheDocument()
})

test('Given a spent OpenAlex allowance, Then the reason shows and Try again waits out the reported wait', async () => {
  mockApi({ 'GET /papers/p1/fulltext': failed('rate_limited', { result: { outcome: 'rate_limited', retry_after: 3600 }, error: { code: 'FULLTEXT_RATE_LIMITED', message: 'Today’s OpenAlex allowance is used up.' } }) })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByText('OpenAlex is limiting requests')).toBeVisible()
  expect(screen.getByText(/Today’s OpenAlex allowance is used up/)).toBeVisible()
  expect(screen.getByText('Try again in 1 hour.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeDisabled()
  expect(screen.getByRole('link', { name: 'Open the paper' })).toHaveAttribute('href', doi)
})

test.each([
  ['unavailable', 'OpenAlex couldn’t be reached', true],
  ['invalid_pdf', 'OpenAlex’s copy isn’t a usable PDF', false],
  ['unsafe_url', 'OpenAlex’s link couldn’t be followed safely', false],
  ['api_key_required', 'OpenAlex didn’t accept the API key', false],
  ['blocked', 'The PDF couldn’t be downloaded', true],
])('Given %s, Then the outcome is explained plainly beside the DOI link', async (outcome, title, retry) => {
  mockApi({ 'GET /papers/p1/fulltext': failed(outcome) })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByRole('alert')).toHaveTextContent(title)
  expect(!!screen.queryByRole('button', { name: 'Try again' })).toBe(retry)
  expect(screen.getByRole('link', { name: 'Open the paper' })).toHaveAttribute('href', doi)
})

test('Given successive deliberate retries, Then each click has a fresh UUID', async () => {
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': failed('unavailable'), 'POST /papers/p1/retrieve-fulltext': { paper_id: 'p1', job_id: 'j2' } })
  const { user } = renderWithProviders(<FullTextAccess paper={paper} />)
  await user.click(await screen.findByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(2))
  const bodies = calls.filter((call) => call.method === 'POST').map((call) => call.body)
  expect(bodies[0]).not.toEqual(bodies[1])
})

test('Given a paper without a DOI, Then only the upload remains', async () => {
  const semantic = { ...openalex, provider: 'semantic_scholar' as const, doi: null }
  mockApi({ 'GET /papers/p1/fulltext': failed('not_stored') })
  const { container } = renderWithProviders(<FullTextAccess paper={{ ...paper, doi: null, sources: [semantic] }} />)
  await waitFor(() => expect(container).toBeEmptyDOMElement())
})

test('Given a completed retrieval while extraction is pending, Then the ingestion references are handed off once', async () => {
  const accepted = vi.fn()
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'completed', result: { outcome: 'downloaded' } }, document_id: 'd1', ingest_job_id: 'ingest-1' }, 'GET /jobs/ingest-1': { id: 'ingest-1', state: 'processing' } })
  const { rerender } = renderWithProviders(<FullTextAccess paper={paper} onAccepted={accepted} />)
  await waitFor(() => expect(accepted).toHaveBeenCalledWith({ paper_id: 'p1', document_id: 'd1', job_id: 'ingest-1' }))
  rerender(<FullTextAccess paper={{ ...paper }} onAccepted={(value) => accepted(value)} />)
  expect(accepted).toHaveBeenCalledTimes(1)
  expect(screen.queryByText(/background/i)).not.toBeInTheDocument()
})

test('Given downloaded bytes whose processing failed, Then retrieval does not restart and the DOI link remains', async () => {
  const accepted = vi.fn()
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'completed' }, document_id: 'd1', ingest_job_id: 'ingest-1' }, 'GET /jobs/ingest-1': { id: 'ingest-1', state: 'failed' } })
  renderWithProviders(<FullTextAccess paper={{ ...paper, document_status: 'failed', active_document_id: 'd1' }} onAccepted={accepted} />)
  expect(await screen.findByRole('link', { name: 'Open the paper' })).toHaveAttribute('href', doi)
  expect(accepted).not.toHaveBeenCalled()
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
})

test.each([
  [{ provider: 'openalex', source: 'content', work_id: 'W123' }, 'Retrieved via OpenAlex'],
  [{ provider: 'openalex', version: 'acceptedVersion', license: 'cc-by', final_url: 'https://arxiv.org/pdf/1' }, 'Retrieved via OpenAlex · Accepted manuscript · License: cc-by'],
])('Given a ready PDF with stored acquisition %o, Then its provenance stays readable', async (acquisition, text) => {
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, document_id: 'd1', acquisition } })
  renderWithProviders(<FullTextAccess paper={{ ...paper, document_status: 'ready', active_document_id: 'd1' }} />)
  expect(await screen.findByText(text)).toBeVisible()
})

test('Given a manually replaced PDF, Then old acquisition details are refreshed immediately', async () => {
  let replaced = false
  mockApi({ 'GET /papers/p1/fulltext': () => Response.json({ ...idle, document_id: replaced ? 'manual' : 'd1', acquisition: replaced ? null : { provider: 'openalex', version: 'acceptedVersion' } }), 'POST /documents': () => { replaced = true; return Response.json({ paper_id: 'p1', document_id: 'manual', job_id: 'ingest-new' }) }, 'GET /jobs/ingest-new': { state: 'processing' } })
  const { user } = renderWithProviders(<><FullTextAccess paper={{ ...paper, document_status: 'ready', active_document_id: 'd1' }} /><UploadDropzone paperId="p1" /></>)
  expect(await screen.findByText(/Retrieved via OpenAlex/)).toBeVisible()
  await user.upload(screen.getByLabelText('PDF file'), new File(['%PDF-1.4'], 'replacement.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  await waitFor(() => expect(screen.queryByText(/Retrieved via OpenAlex/)).not.toBeInTheDocument())
})

test('Given a newer manual document is processing, Then stale retrieval references do not change the followed document', async () => {
  const accepted = vi.fn()
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'completed' }, document_id: 'old-doc', ingest_job_id: 'old-ingest' }, 'GET /jobs/old-ingest': { id: 'old-ingest', state: 'completed' } })
  renderWithProviders(<FullTextAccess paper={{ ...paper, document_status: 'processing', active_document_id: 'manual-doc' }} onAccepted={accepted} />)
  await waitFor(() => expect(calls.some((call) => call.path === '/jobs/old-ingest')).toBe(true))
  expect(accepted).not.toHaveBeenCalled()
})
