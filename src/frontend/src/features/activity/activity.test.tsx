import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'

const base = { attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, available_at: '2026-10-08T10:00:00Z', created_at: '2026-10-08T10:00:00Z', updated_at: '2026-10-08T10:05:00Z' }
const failed = { ...base, id: 'j1', kind: 'ingest', state: 'failed', stage: 'failed', progress: 30, attempts: 2, error: { code: 'PDF_UNREADABLE', message: 'The PDF has no extractable text.' }, paper_id: 'p1', paper_title: 'Traceable research systems' }
const summary = { ...base, id: 'j2', kind: 'summary', state: 'completed', stage: 'completed', progress: 100, paper_id: 'p2', paper_title: 'Attention is all you need' }
const running = { ...base, id: 'j3', kind: 'ingest', state: 'processing', stage: 'extracting_metadata', progress: 55, paper_id: null, paper_title: null }
afterEach(() => vi.unstubAllGlobals())
// Local model tests run with open models on, as the server reports them (ARA-090).
const openModels = { 'GET /features': { open_models: true } }

test('Given a failed retrieval, When Retry download is pressed, Then a fresh full-text request targets its paper', async () => {
  const job = { ...failed, kind: 'fulltext', error: { code: 'FULLTEXT_BLOCKED', message: 'This site blocked the download.' } }
  const { calls } = mockApi({ 'GET /jobs': { items: [job] }, 'POST /papers/p1/retrieve-fulltext': { paper_id: 'p1', job_id: 'j-new' } })
  const { user } = renderApp('/activity')
  const row = (await screen.findByRole('heading', { name: 'PDF retrieval' })).closest('li') as HTMLElement
  expect(within(row).getByRole('link', { name: failed.paper_title })).toHaveAttribute('href', '/papers/p1')
  await user.click(within(row).getByRole('button', { name: 'Retry download' }))
  await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1))
  expect(calls.find((call) => call.method === 'POST')).toMatchObject({ path: '/papers/p1/retrieve-fulltext', body: { request_id: expect.stringMatching(/^[0-9a-f-]{36}$/) } })
  expect(calls.some((call) => call.path.endsWith('/retry'))).toBe(false)
})

test('Given a rate-limited retrieval in Activity, Then its retry respects the reported wait', async () => {
  mockApi({ 'GET /jobs': { items: [{ ...failed, kind: 'fulltext', updated_at: new Date().toISOString(), result: { outcome: 'rate_limited', retry_after: 60 } }] } })
  renderApp('/activity')
  expect(await screen.findByRole('button', { name: 'Retry download' })).toBeDisabled()
  expect(screen.getByText(/Try again in/)).toBeVisible()
})

test.each(['queued', 'verifying'])('Given a %s verification-only job, Then Activity names preparation and shows background status without transfer percentages', async (stage) => {
  const model = { key: 'ifm-k2-horizon-7b', display_name: 'K2 Horizon 7B', status: 'unavailable', reasoning_efforts: ['default'] }
  mockApi({ ...openModels, 'GET /models': { items: [model] }, 'GET /jobs': { items: [{ ...base, id: 'prepare-job', kind: 'model_download', model_operation: 'verify', model_key: model.key, state: stage === 'queued' ? 'queued' : 'processing', stage, progress: 80, completed_bytes: 5592218900, total_bytes: 5592218900 }] } })
  renderApp('/activity')
  const row = (await screen.findByRole('heading', { name: 'Model preparation' })).closest('li') as HTMLElement
  expect(within(row).getByRole('link', { name: 'K2 Horizon 7B' })).toHaveAttribute('href', '/settings#local-models')
  expect(within(row).getByRole('status')).toHaveTextContent(stage === 'queued' ? 'Waiting to check model readiness' : 'Checking model readiness')
  expect(within(row).getByText(/continues in the background/)).toBeVisible()
  expect(within(row).queryByText(/\d+%/)).not.toBeInTheDocument()
  expect(within(row).queryByRole('progressbar')).not.toBeInTheDocument()
})

test.each(['failed', 'completed'])('Given a %s verification-only job, Then Activity retains its preparation identity', async (state) => {
  mockApi({ ...openModels, 'GET /jobs': { items: [{ ...base, id: 'prepare-job', kind: 'model_download', model_operation: 'verify', model_key: 'ifm-k2-horizon-7b', state, stage: state, progress: state === 'completed' ? 100 : 80, error: state === 'failed' ? { code: 'LOCAL_MODEL_VERIFICATION_FAILED', message: 'Model preparation failed. Retry in Settings.' } : null }] } })
  renderApp('/activity')
  const row = (await screen.findByRole('heading', { name: 'Model preparation' })).closest('li') as HTMLElement
  expect(within(row).getByText(state === 'failed' ? 'Failed' : 'Completed')).toBeVisible()
  if (state === 'failed') expect(within(row).getByText('Model preparation failed. Retry in Settings.')).toBeVisible()
  expect(within(row).queryByRole('progressbar')).not.toBeInTheDocument()
})

test('Given a paused model download, Then Activity names the model and links to its management controls', async () => {
  const model = { key: 'ifm-k2-horizon-7b', display_name: 'K2 Horizon 7B', status: 'unavailable', reasoning_efforts: ['default'] }
  mockApi({ ...openModels, 'GET /models': { items: [model] }, 'GET /jobs': { items: [{ ...base, id: 'model-job', kind: 'model_download', model_key: model.key, state: 'paused', stage: 'paused', progress: 25, completed_bytes: 1398054725, total_bytes: 5592218900 }] } })
  const { user } = renderApp('/activity')
  const row = (await screen.findByRole('heading', { name: 'Model download' })).closest('li') as HTMLElement
  expect(within(row).getByRole('link', { name: 'K2 Horizon 7B' })).toHaveAttribute('href', '/settings#local-models')
  expect(within(row).getAllByText('Paused').length).toBeGreaterThan(0)
  await user.click(screen.getByRole('radio', { name: 'Active' }))
  expect(screen.getByRole('heading', { name: 'Model download' })).toBeVisible()
})

test('Given a failed ingest job, When Retry processing is pressed, Then it is queued again and links to its paper', async () => {
  const { calls } = mockApi({ 'GET /jobs': { items: [failed, summary] }, 'POST /jobs/j1/retry': { ...failed, state: 'queued', stage: 'queued', error: null } })
  const { user } = renderApp('/activity')
  expect(await screen.findByRole('heading', { level: 1, name: 'Activity' })).toBeVisible()
  const row = (await screen.findByRole('heading', { level: 2, name: 'PDF processing' })).closest('li') as HTMLElement
  expect(within(row).getByRole('link', { name: failed.paper_title })).toHaveAttribute('href', '/papers/p1')
  expect(within(row).getByText('Failed')).toBeVisible()
  expect(within(row).getByText('The PDF has no extractable text.')).toBeVisible()
  await user.click(within(row).getByRole('button', { name: 'Retry processing' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/jobs/j1/retry')).toBe(true))
  expect(await screen.findByText('Processing queued again')).toBeVisible()
  const done = (screen.getByRole('heading', { level: 2, name: 'Paper summary' })).closest('li') as HTMLElement
  expect(within(done).getByRole('link', { name: summary.paper_title })).toHaveAttribute('href', '/papers/p2')
  expect(within(done).queryByRole('button', { name: 'Retry processing' })).not.toBeInTheDocument()
})

test('Given active and finished jobs, Then stage and progress are readable and the filter narrows the list', async () => {
  mockApi({ 'GET /jobs': { items: [running, failed, summary] } })
  const { user } = renderApp('/activity')
  expect(await screen.findByText('Extracting title, authors and abstract')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'PDF processing progress' })).toBeVisible()
  expect(within(screen.getByRole('list', { name: 'Jobs' })).getAllByRole('listitem')).toHaveLength(3)
  await user.click(screen.getByRole('radio', { name: 'Failed' }))
  await waitFor(() => expect(within(screen.getByRole('list', { name: 'Jobs' })).getAllByRole('listitem')).toHaveLength(1))
  expect(screen.getByRole('link', { name: failed.paper_title })).toBeVisible()
  await user.click(screen.getByRole('radio', { name: 'Active' }))
  await waitFor(() => expect(within(screen.getByRole('list', { name: 'Jobs' })).getAllByRole('listitem')).toHaveLength(1))
  expect(screen.getByText('55%')).toBeVisible()
})

test('Given the legacy jobs route, Then Activity opens with an empty state', async () => {
  mockApi({})
  renderApp('/jobs')
  expect(await screen.findByRole('heading', { level: 1, name: 'Activity' })).toBeVisible()
  expect(await screen.findByRole('heading', { name: 'No activity yet' })).toBeVisible()
  expect(within(screen.getByRole('main')).getByRole('link', { name: 'Upload a PDF' })).toHaveAttribute('href', '/library#upload')
})
