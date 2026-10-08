// Test-after coverage (ARA-038): these behaviours shipped before their tests. Each test was checked
// against a deliberate mutation of the implementation to confirm it can fail.
import { screen, waitFor, within } from '@testing-library/react'
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

test('Given an unknown job kind, Then it is named as a job instead of a raw code', async () => {
  mockApi({ 'GET /jobs': { items: [{ ...done, id: 'c1', kind: 'canary' }, { ...done, id: 'c2', kind: 'pdf_export' }] } })
  renderApp('/activity')
  expect(await screen.findByRole('heading', { level: 2, name: 'Canary job' })).toBeVisible()
  expect(screen.getByRole('heading', { level: 2, name: 'Pdf export job' })).toBeVisible()
})

test('Given only finished jobs, When Active or Failed is chosen, Then a filter-specific empty state appears', async () => {
  mockApi({ 'GET /jobs': { items: [done] } })
  const { user } = renderApp('/activity')
  await waitFor(() => expect(within(jobsList()).getAllByRole('listitem')).toHaveLength(1))
  await user.click(screen.getByRole('radio', { name: 'Active' }))
  expect(await screen.findByRole('heading', { name: 'Nothing is running' })).toBeVisible()
  expect(screen.getByText('New uploads and summaries show their progress here while they run.')).toBeVisible()
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
