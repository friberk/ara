// Test-after coverage (ARA-038): these behaviours shipped before their tests. Each test was checked
// against a deliberate mutation of the implementation to confirm it can fail.
import { screen, waitFor, within } from '@testing-library/react'
import { toast } from 'sonner'
import { renderApp } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'

const base = { attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, paper_id: null, paper_title: null, available_at: '2026-10-08T10:00:00Z' }
const done = { ...base, id: 'j1', kind: 'summary', state: 'completed', stage: 'completed', progress: 100, created_at: '2026-10-08T11:50:00Z', updated_at: '2026-10-08T11:55:00Z' }
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const jobsList = () => screen.getByRole('list', { name: 'Jobs' })

test('Given jobs at different times, Then each shows when it started, finished or failed relative to now', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-08T12:00:00Z'))
  mockApi({ 'GET /jobs': { items: [
    { ...base, id: 'j0', kind: 'ingest', state: 'processing', stage: 'processing', progress: 10, created_at: '2026-10-08T11:59:40Z', updated_at: '2026-10-08T11:59:50Z' },
    done,
    { ...base, id: 'j2', kind: 'ingest', state: 'failed', stage: 'failed', progress: 30, error: { code: 'X', message: 'Unreadable PDF.' }, created_at: '2026-10-07T11:00:00Z', updated_at: '2026-10-07T12:00:00Z' },
  ] } })
  renderApp('/activity')
  const started = await screen.findByText('Started just now')
  expect(started.tagName).toBe('TIME')
  expect(started).toHaveAttribute('datetime', '2026-10-08T11:59:40Z')
  expect(screen.getByText('Finished 5 minutes ago')).toHaveAttribute('datetime', done.updated_at)
  expect(screen.getByText('Failed yesterday')).toHaveAttribute('datetime', '2026-10-07T12:00:00Z')
})

test('Given internal maintenance jobs, Then Activity lists only PDF processing and paper summaries', async () => {
  // Finish review: internal diagnostics (the canary) are not the reader's work and must not appear.
  mockApi({ 'GET /jobs': { items: [{ ...done, id: 'c1', kind: 'canary' }, { ...done, id: 'c2', kind: 'pdf_export' }, { ...done, id: 's1', kind: 'summary' }] } })
  renderApp('/activity')
  expect(await screen.findByRole('heading', { level: 2, name: 'Paper summary' })).toBeVisible()
  expect(within(jobsList()).getAllByRole('listitem')).toHaveLength(1)
  expect(screen.queryByRole('heading', { name: /Canary|Pdf export/ })).not.toBeInTheDocument()
})

test('Given only internal jobs, Then Activity shows its empty state', async () => {
  mockApi({ 'GET /jobs': { items: [{ ...done, id: 'c1', kind: 'canary' }] } })
  renderApp('/activity')
  expect(await screen.findByRole('heading', { name: 'No activity yet' })).toBeVisible()
})

test('Given only finished jobs, When Active or Failed is chosen, Then a filter-specific empty state appears', async () => {
  mockApi({ 'GET /jobs': { items: [done] } })
  const { user } = renderApp('/activity')
  await waitFor(() => expect(within(jobsList()).getAllByRole('listitem')).toHaveLength(1))
  await user.click(screen.getByRole('radio', { name: 'Active' }))
  expect(await screen.findByRole('heading', { name: 'Nothing is running' })).toBeVisible()
  // Open models are off by default, so the copy leaves out model downloads (ARA-090).
  expect(screen.getByText('Uploads and summaries show their progress here.')).toBeVisible()
  expect(screen.queryByRole('list', { name: 'Jobs' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('radio', { name: 'Failed' }))
  expect(await screen.findByRole('heading', { name: 'No failed jobs' })).toBeVisible()
  await user.click(screen.getByRole('radio', { name: 'All' }))
  expect(within(jobsList()).getAllByRole('listitem')).toHaveLength(1)
})

test('Given activity is loading, Then skeleton rows are announced', async () => {
  mockApi({ 'GET /jobs': () => new Promise<Response>(() => {}) })
  renderApp('/activity')
  await waitFor(() => expect(screen.getAllByRole('status').some((element) => element.textContent?.includes('Loading activity…'))).toBe(true))
  const status = screen.getAllByRole('status').find((element) => element.textContent?.includes('Loading activity…')) as HTMLElement
  expect(status.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThanOrEqual(3)
})

test('Given jobs cannot load, Then the error is shown inline and Try again reloads them', async () => {
  let failing = true
  mockApi({ 'GET /jobs': () => (failing ? json({ code: 'DATABASE_UNAVAILABLE', message: 'Jobs are unavailable right now.', request_id: 'r1' }, 503) : json({ items: [done] })) })
  const { user } = renderApp('/activity')
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Jobs are unavailable right now.')
  failing = false
  await user.click(within(alert).getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(within(jobsList()).getAllByRole('listitem')).toHaveLength(1))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

describe('retrying a failed ingest job', () => {
  // Sonner keeps toasts in a module-level store and replays active ones to a new Toaster; clear them between tests.
  afterEach(() => { toast.dismiss() })
  const failedJob = { ...base, id: 'j9', kind: 'ingest', state: 'failed', stage: 'failed', progress: 30, error: { code: 'PDF_UNREADABLE', message: 'The PDF has no extractable text.' }, paper_id: 'p1', paper_title: 'Traceable research systems', created_at: '2026-10-08T10:00:00Z', updated_at: '2026-10-08T10:05:00Z' }
  const rowOf = async () => (await screen.findByRole('heading', { level: 2, name: 'PDF processing' })).closest('li') as HTMLElement

  test('Given a retry in flight, Then the button reads Retrying… and stays disabled until it is queued', async () => {
    let finish: (response: Response) => void = () => {}
    mockApi({ 'GET /jobs': { items: [failedJob] }, 'POST /jobs/j9/retry': () => new Promise<Response>((done) => { finish = done }) })
    const { user } = renderApp('/activity')
    const row = await rowOf()
    await user.click(within(row).getByRole('button', { name: 'Retry processing' }))
    expect(await within(row).findByRole('button', { name: 'Retrying…' })).toBeDisabled()
    finish(json({ ...failedJob, state: 'queued', stage: 'queued', error: null }))
    expect(await screen.findByText('Processing queued again')).toBeVisible()
  })

  test('Given the retry is refused, Then the reason is shown inline in the row and retrying stays possible', async () => {
    mockApi({ 'GET /jobs': { items: [failedJob] }, 'POST /jobs/j9/retry': () => json({ code: 'JOB_NOT_RETRYABLE', message: 'This job can no longer be retried.', request_id: 'r1' }, 409) })
    const { user } = renderApp('/activity')
    const row = await rowOf()
    await user.click(within(row).getByRole('button', { name: 'Retry processing' }))
    expect(await within(row).findByRole('alert')).toHaveTextContent('This job can no longer be retried.')
    expect(within(row).getByRole('button', { name: 'Retry processing' })).toBeEnabled()
    expect(screen.queryByText('Processing queued again')).not.toBeInTheDocument()
  })
})
