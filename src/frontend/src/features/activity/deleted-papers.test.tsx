// Work for papers that were deleted (ARA-095).
import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'

const base = { attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, available_at: '2026-10-10T10:00:00Z', created_at: '2026-10-10T10:00:00Z', updated_at: '2026-10-10T10:05:00Z' }
const stopped = { ...base, id: 'j1', kind: 'summary', state: 'failed', stage: 'failed', progress: 40, error_code: 'PAPER_DELETED', error: { code: 'PAPER_DELETED', message: 'Stopped because the paper was deleted.' }, result: { outcome: 'paper_deleted', paper_title: 'Attention is all you need' }, paper_id: null, paper_title: 'Attention is all you need' }
const cleanup = { ...base, id: 'j2', kind: 'storage_cleanup', state: 'failed', stage: 'failed', progress: 0, attempts: 3, error_code: 'STORAGE_UNAVAILABLE', error: { code: 'STORAGE_UNAVAILABLE', message: 'Storage is unavailable, so the deleted PDFs are not removed yet.' }, paper_id: null, paper_title: null }
afterEach(() => vi.unstubAllGlobals())

test('Given work stopped because its paper was deleted, Then Activity shows it as cancelled and names the paper without a link', async () => {
  mockApi({ 'GET /jobs': { items: [stopped] } })
  const { user } = renderApp('/activity')
  const row = (await screen.findByRole('heading', { name: 'Paper summary' })).closest('li') as HTMLElement
  expect(within(row).getByText('Cancelled')).toBeVisible()
  expect(within(row).getByText('Attention is all you need (deleted)')).toBeVisible()
  expect(within(row).queryByRole('link')).not.toBeInTheDocument()
  expect(within(row).getByText('Stopped because the paper was deleted.')).not.toHaveClass('text-destructive')
  expect(within(row).queryByRole('button')).not.toBeInTheDocument()
  // Cancelled work is not a failure.
  await user.click(screen.getByRole('radio', { name: 'Failed' }))
  expect(await screen.findByRole('heading', { name: 'No failed jobs' })).toBeVisible()
})

test('Given the cleanup of deleted papers failed, Then Activity names it and it can be retried', async () => {
  const { calls } = mockApi({ 'GET /jobs': { items: [cleanup] }, 'POST /jobs/j2/retry': () => json({ ...cleanup, state: 'queued', stage: 'queued', error: null }, 202) })
  const { user } = renderApp('/activity')
  const row = (await screen.findByRole('heading', { name: 'Deleted PDF cleanup' })).closest('li') as HTMLElement
  expect(within(row).getByText('Storage is unavailable, so the deleted PDFs are not removed yet.')).toBeVisible()
  await user.click(within(row).getByRole('button', { name: 'Retry cleanup' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/jobs/j2/retry')).toBe(true))
})
