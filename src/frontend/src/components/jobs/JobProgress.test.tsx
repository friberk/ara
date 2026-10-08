import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'
import { JobProgress } from './JobProgress'

afterEach(() => vi.unstubAllGlobals())
const job = (overrides: Record<string, unknown>) => ({ id: 'job1', kind: 'ingest', state: 'processing', stage: 'processing', progress: 40, attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, available_at: '2026-10-08T00:00:00Z', created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', paper_id: null, paper_title: null, ...overrides })

test('Given a running job, Then its readable stage and progress are shown', async () => {
  mockApi({ 'GET /jobs/job1': job({ stage: 'summarizing', progress: 40 }) })
  renderWithProviders(<JobProgress jobId="job1" />)
  expect(await screen.findByText('Summarizing sections')).toBeVisible()
  expect(screen.getByText('40%')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'Processing progress' })).toBeVisible()
})

test('Given a completed job, When the parent rerenders, Then completion is announced once', async () => {
  mockApi({ 'GET /jobs/job1': job({ state: 'completed', stage: 'completed', progress: 100 }) })
  const settled = vi.fn()
  const view = renderWithProviders(<JobProgress jobId="job1" onSettled={(value) => settled(value)} />)
  await screen.findByText('Completed')
  await waitFor(() => expect(settled).toHaveBeenCalledTimes(1))
  view.rerender(<JobProgress jobId="job1" onSettled={(value) => settled(value)} />)
  expect(settled).toHaveBeenCalledTimes(1)
})

test('Given a failed job, Then the failure and its message are shown', async () => {
  mockApi({ 'GET /jobs/job1': job({ state: 'failed', stage: 'failed', error_code: 'PDF_UNREADABLE', error_message: 'The PDF has no extractable text.', error: { code: 'PDF_UNREADABLE', message: 'The PDF has no extractable text.' } }) })
  renderWithProviders(<JobProgress jobId="job1" />)
  expect(await screen.findByText('Processing failed')).toBeVisible()
  expect(screen.getByText('The PDF has no extractable text.')).toBeVisible()
})
