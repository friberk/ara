import { screen, waitFor } from '@testing-library/react'
import { focusManager } from '@tanstack/react-query'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { useFullText, useRetrieveFullText } from './fulltext'

function Probe() {
  const status = useFullText('p1')
  const request = useRetrieveFullText('p1')
  return <><p>{String(status.data?.api_key_configured)}</p><button onClick={() => request.mutate({ request_id: 'f997f1dc-2236-4cda-b827-0b94d889aa00' })}>Submit</button><p>{request.data?.job_id}</p></>
}
afterEach(() => { vi.unstubAllGlobals(); focusManager.setFocused(undefined) })

test('Given a transport failure, When the same mutation retries, Then its UUID is unchanged', async () => {
  let attempts = 0
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { paper_id: 'p1', api_key_configured: true }, 'POST /papers/p1/retrieve-fulltext': () => { if (++attempts === 1) throw new TypeError('Network lost'); return Response.json({ paper_id: 'p1', job_id: 'j1' }) } })
  const { user } = renderWithProviders(<Probe />)
  await user.click(screen.getByRole('button', { name: 'Submit' }))
  expect(await screen.findByText('j1', {}, { timeout: 3000 })).toBeVisible()
  const posts = calls.filter((call) => call.method === 'POST')
  expect(posts).toHaveLength(2)
  expect(posts.map((call) => call.body)).toEqual(Array(2).fill({ request_id: 'f997f1dc-2236-4cda-b827-0b94d889aa00' }))
})

test('Given terminal persisted state, When focus returns, Then state is read without submitting a request', async () => {
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { paper_id: 'p1', api_key_configured: true } })
  renderWithProviders(<Probe />)
  expect(await screen.findByText('true')).toBeVisible()
  const before = calls.length
  focusManager.setFocused(false)
  focusManager.setFocused(true)
  await waitFor(() => expect(calls.length).toBeGreaterThan(before))
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
})

test('Given completed retrieval with pending ingestion, Then ingestion is followed and status continues polling', async () => {
  const { calls } = mockApi({ 'GET /papers/p1/fulltext': { paper_id: 'p1', retrieval_job: { id: 'j1', state: 'completed' }, document_id: 'd1', ingest_job_id: 'ingest-1' }, 'GET /jobs/ingest-1': { id: 'ingest-1', state: 'processing' } })
  renderWithProviders(<Probe />)
  await waitFor(() => expect(calls.some((call) => call.path === '/jobs/ingest-1')).toBe(true))
  await waitFor(() => expect(calls.filter((call) => call.path === '/papers/p1/fulltext').length).toBeGreaterThan(1), { timeout: 3000 })
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
})
