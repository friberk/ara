import { screen, waitFor } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { FullTextAccess } from './FullTextAccess'
import { UploadDropzone } from '@/components/upload/UploadDropzone'

const source = { provider: 'semantic_scholar' as const, external_id: 's2-paper', title: 'Research', authors: [], year: null, abstract: null, doi: '10.5555/paper', external_url: 'https://www.semanticscholar.org/paper/s2-paper', pdf_url: null }
const paper: Paper = { id: 'p1', title: 'Research', authors: [], year: null, abstract: null, doi: source.doi, document_status: 'metadata_only', active_document_id: null, sources: [source], metadata_provenance: {} }
const idle = { paper_id: 'p1', availability: 'unknown', locations: [], retrieval_job: null, document_id: null, ingest_job_id: null, attempts: [] }
const job = { id: 'j1', kind: 'fulltext', state: 'processing', stage: 'discovering_fulltext', progress: 10, result: null }
const copy = { pdf_url: 'https://arxiv.org/pdf/paper', is_oa: true }
const automatic = 'POST /papers/p1/retrieve-fulltext/automatic'
afterEach(() => vi.unstubAllGlobals())

test('Given a saved paper with no attempt yet, When its workspace opens, Then retrieval starts once by itself and shows one progress line', async () => {
  let started = false
  const { calls } = mockApi({
    'GET /papers/p1/fulltext': () => Response.json({ ...idle, locations: [copy], retrieval_job: started ? { ...job, state: 'queued', stage: 'queued' } : null }),
    [automatic]: () => { started = true; return Response.json({ paper_id: 'p1', job_id: 'j1' }) },
  })
  // The reader and the Details tab both show retrieval; together they still ask once.
  renderWithProviders(<><FullTextAccess paper={paper} /><FullTextAccess paper={paper} /></>)
  expect((await screen.findAllByText('Looking for an open PDF'))[0]).toBeVisible()
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1))
  expect(calls.find((call) => call.method === 'POST')?.path).toBe('/papers/p1/retrieve-fulltext/automatic')
  expect(screen.queryByRole('button', { name: /Get PDF|Find PDF/ })).not.toBeInTheDocument()
  expect(screen.queryByText(/background/i)).not.toBeInTheDocument()
})

test('Given a download in progress, Then the progress names the source it comes from', async () => {
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, locations: [copy], retrieval_job: { ...job, stage: 'fetching_pdf', progress: 40 }, source_host: 'arxiv.org' } })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByText('Downloading the PDF from arXiv')).toBeVisible()
  expect(screen.getByRole('status')).toHaveTextContent('Downloading the PDF from arXiv')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('Given no PDF link and no DOI, Then nothing starts by itself and Find PDF stays available', async () => {
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': idle })
  renderWithProviders(<FullTextAccess paper={{ ...paper, doi: null, sources: [{ ...source, doi: null }] }} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Find PDF' })).toBeEnabled())
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
})

test('Given the paper does not qualify, When the server starts nothing, Then Find PDF is offered', async () => {
  mockApi({ 'GET /papers/p1/fulltext': idle, [automatic]: { paper_id: 'p1', job_id: null } })
  renderWithProviders(<FullTextAccess paper={paper} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Find PDF' })).toBeEnabled())
})

test.each([
  ['access_required', 'This PDF needs a sign-in', true, true],
  ['blocked', 'The source blocked the download', true, true],
  ['invalid_pdf', 'The link didn’t return a usable PDF', false, true],
  ['unsupported_source', 'Automatic downloads aren’t enabled for this site', false, true],
  ['unsafe_url', 'This link can’t be downloaded safely', false, false],
  ['not_found', 'The PDF link no longer works', false, false],
  ['no_pdf_link', 'No open PDF was found', false, false],
  ['unavailable', 'The PDF couldn’t be reached right now', true, false],
])('Given %s, Then the outcome is explained plainly with only the actions that can help', async (outcome, title, retry, browser) => {
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, locations: [copy], retrieval_job: { ...job, state: 'failed', stage: 'failed', result: { outcome } } } })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByRole('alert')).toHaveTextContent(title)
  expect(screen.queryByText(/paywall/i)).not.toBeInTheDocument()
  expect(!!screen.queryByRole('button', { name: 'Try again' })).toBe(retry)
  expect(!!screen.queryByRole('link', { name: 'Open PDF in browser' })).toBe(browser)
  if (browser) expect(screen.getByRole('link', { name: 'Open PDF in browser' })).toHaveAttribute('href', copy.pdf_url)
  expect(screen.getByRole('link', { name: 'Open publisher' })).toHaveAttribute('href', 'https://doi.org/10.5555/paper')
})

test('Given a completed retrieval while extraction is pending, Then the original ingestion references are handed off once without boilerplate', async () => {
  const accepted = vi.fn()
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'completed', result: { outcome: 'downloaded' } }, document_id: 'd1', ingest_job_id: 'ingest-1' }, 'GET /jobs/ingest-1': { id: 'ingest-1', state: 'processing' } })
  const { rerender } = renderWithProviders(<FullTextAccess paper={paper} onAccepted={accepted} />)
  await waitFor(() => expect(accepted).toHaveBeenCalledWith({ paper_id: 'p1', document_id: 'd1', job_id: 'ingest-1' }))
  rerender(<FullTextAccess paper={{ ...paper }} onAccepted={(value) => accepted(value)} />)
  expect(accepted).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('button', { name: 'Find PDF' })).not.toBeInTheDocument()
  expect(screen.queryByText(/background/i)).not.toBeInTheDocument()
})

test('Given downloaded bytes whose ingestion failed, Then retrieval does not restart the processing gate', async () => {
  const accepted = vi.fn()
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'completed' }, document_id: 'd1', ingest_job_id: 'ingest-1' }, 'GET /jobs/ingest-1': { id: 'ingest-1', state: 'failed' } })
  renderWithProviders(<FullTextAccess paper={{ ...paper, document_status: 'failed', active_document_id: 'd1' }} onAccepted={accepted} />)
  await waitFor(() => expect(calls.some((call) => call.path === '/jobs/ingest-1')).toBe(true))
  expect(accepted).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Find PDF' })).toBeEnabled()
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
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

test('Given a ready manual PDF beside an old failure, Then the acquisition details appear without retry warnings', async () => {
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'failed', result: { outcome: 'blocked' } }, acquisition: { provider: 'openalex', version: 'acceptedVersion', license: 'cc-by' } } })
  renderWithProviders(<FullTextAccess paper={{ ...paper, document_status: 'ready', active_document_id: 'manual-doc' }} />)
  expect(await screen.findByText(/Accepted manuscript/)).toBeVisible()
  expect(screen.getByText(/cc-by/)).toBeVisible()
  expect(screen.queryByText(/blocked/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
})

test('Given a rate limit, Then the reason is shown and Try again waits out the reported wait', async () => {
  mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'failed', updated_at: new Date().toISOString(), error: { code: 'FULLTEXT_RATE_LIMITED', message: 'Semantic Scholar is limiting lookups; some copies went unchecked.' }, result: { outcome: 'rate_limited', retry_after: 60 } } } })
  renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests right now')
  expect(screen.getByText(/Semantic Scholar is limiting lookups/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeDisabled()
  expect(screen.getByText(/Try again in (59|60) seconds/)).toBeVisible()
})

test('Given successive deliberate retries, Then each click has a fresh UUID and unsafe record links stay hidden', async () => {
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: { ...job, state: 'failed', result: { outcome: 'blocked' } } }, 'POST /papers/p1/retrieve-fulltext': { paper_id: 'p1', job_id: 'j2' } })
  const { user } = renderWithProviders(<FullTextAccess paper={{ ...paper, sources: [{ ...source, external_url: 'javascript:alert(1)' }] }} />)
  await user.click(await screen.findByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(2))
  const bodies = calls.filter((call) => call.method === 'POST').map((call) => call.body)
  expect(bodies[0]).not.toEqual(bodies[1])
  expect(screen.queryByRole('link', { name: 'Open Semantic Scholar' })).not.toBeInTheDocument()
})

test('Given blocked access, Then network guidance and safe browser links accompany a fresh deliberate retry', async () => {
  const denied = { ...job, state: 'failed', stage: 'failed', result: { outcome: 'blocked' } }
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { ...idle, retrieval_job: denied }, 'POST /papers/p1/retrieve-fulltext': { paper_id: 'p1', job_id: 'j2' } })
  const { user } = renderWithProviders(<FullTextAccess paper={paper} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('The source blocked the download')
  expect(screen.getByText(/try again on its network or VPN/)).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open Semantic Scholar' })).toHaveAttribute('href', source.external_url)
  expect(screen.getByRole('link', { name: 'Open publisher' })).toHaveAttribute('href', 'https://doi.org/10.5555/paper')
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1))
  expect(calls.find((call) => call.method === 'POST')?.path).toBe('/papers/p1/retrieve-fulltext')
})
