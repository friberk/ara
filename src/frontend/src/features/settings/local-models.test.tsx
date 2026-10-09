import { act, screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'
import type { Model, ModelInstallation } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const installation: ModelInstallation = { state: 'missing', weights_present: false, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 0, total_bytes: 5592218900, job_id: null, digest: null, updated_at: null, error: null }
const local: Model = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', status: 'unavailable', reasoning_efforts: ['default'], context_window: 8192, unavailable_reason: 'Download weights in Settings to use this model.', unavailable_code: 'MODEL_WEIGHTS_MISSING', installation }
const defaults = { default_model: luna.key, reasoning_effort: 'low' }
const job = { id: 'b24b9f87-6035-4f72-b5f8-850d10d9fc57', kind: 'model_download', state: 'queued', stage: 'queued', progress: 0, attempts: 0, generation: 1, result: null, error_code: null, error_message: null, available_at: '2026-10-08T22:00:00Z', created_at: '2026-10-08T22:00:00Z', updated_at: '2026-10-08T22:00:00Z', error: null, model_key: local.key }
const stale: Model = { ...local, unavailable_code: 'LOCAL_MODEL_REVALIDATION_REQUIRED', unavailable_reason: 'Verify this model for the current runtime.', installation: { ...installation, state: 'ready', weights_present: true } }
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

test('Given the model settings anchor, When data arrives, Then the controls scroll into view and receive focus', async () => {
  const scroll = vi.spyOn(Element.prototype, 'scrollIntoView')
  mockApi({ 'GET /models': { items: [luna, local] }, 'GET /settings': defaults })
  renderApp('/settings#local-models')
  const heading = await screen.findByRole('heading', { name: 'Local models' })
  const section = document.getElementById('local-models')
  await waitFor(() => expect(heading).toHaveFocus())
  expect(scroll.mock.contexts).toContain(section)
  scroll.mockRestore()
})

test('Given verification in progress, When weights become ready, Then the persistent live status announces completion', async () => {
  let model: Model = { ...local, installation: { ...installation, state: 'verifying', weights_present: true, job_id: job.id } }
  mockApi({ 'GET /models': () => json({ items: [luna, model] }), 'GET /settings': defaults })
  const { client } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  const status = within(row).getByRole('status')
  expect(status).toHaveTextContent('Preparing model')
  model = { ...local, status: 'available', installation: { ...installation, state: 'ready', weights_present: true } }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await waitFor(() => expect(status).toHaveTextContent('Installed'))
  expect(status).toBeInTheDocument()
})

test('Given missing local weights, Then Settings exposes their identity, size and a download action', async () => {
  mockApi({ 'GET /models': { items: [luna, local] }, 'GET /settings': defaults })
  renderApp('/settings')
  expect(await screen.findByRole('heading', { name: 'Local models' })).toBeVisible()
  const row = screen.getByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByText(local.model_id)).toBeVisible()
  expect(within(row).getByText(/5\.59 GB/)).toBeVisible()
  expect(within(row).getByRole('button', { name: `Download ${local.display_name}` })).toBeEnabled()
  expect(screen.getByText(/Downloads continue in the background/)).toBeVisible()
  expect(screen.getByRole('radio', { name: local.display_name })).toBeDisabled()
})

test('Given an accepted download, When Settings is remounted, Then durable progress returns without another download', async () => {
  let model = local
  const { calls } = mockApi({
    'GET /models': () => json({ items: [luna, model] }), 'GET /settings': defaults,
    [`POST /models/${local.key}/download`]: () => { model = { ...local, installation: { ...installation, state: 'downloading', completed_bytes: 1398054725, job_id: job.id } }; return json(job, 202) },
  })
  const first = renderApp('/settings')
  await first.user.click(await screen.findByRole('button', { name: `Download ${local.display_name}` }))
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  await waitFor(() => expect(within(row).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25'))
  first.unmount()
  renderApp('/settings')
  expect(await screen.findByRole('button', { name: `Pause ${local.display_name} download` })).toBeEnabled()
  expect(calls.filter((call) => call.method === 'POST' && call.path.endsWith('/download'))).toHaveLength(1)
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ request_id: expect.any(String) })
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given a downloading model, When paused and resumed, Then each operation uses the existing durable job', async () => {
  let model: Model = { ...local, installation: { ...installation, state: 'downloading', completed_bytes: 1000, job_id: job.id } }
  const { calls } = mockApi({
    'GET /models': () => json({ items: [luna, model] }), 'GET /settings': defaults,
    [`POST /jobs/${job.id}/pause`]: () => { model = { ...model, installation: { ...installation, completed_bytes: 1000, job_id: job.id, state: 'paused' } }; return json({ ...job, state: 'paused', stage: 'paused' }, 202) },
    [`POST /jobs/${job.id}/resume`]: () => { model = { ...model, installation: { ...installation, completed_bytes: 1000, job_id: job.id, state: 'queued' } }; return json(job, 202) },
  })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('button', { name: `Pause ${local.display_name} download` }))
  await user.click(await screen.findByRole('button', { name: `Resume ${local.display_name} download` }))
  expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([`/jobs/${job.id}/pause`, `/jobs/${job.id}/resume`])
})

test('Given unknown transfer size, Then progress is indeterminate rather than an invented percentage', async () => {
  mockApi({ 'GET /models': { items: [{ ...local, installation: { ...installation, state: 'downloading', total_bytes: null, completed_bytes: 1024, job_id: job.id } }] }, 'GET /settings': defaults })
  renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  expect(within(row).getByText(/Size pending/)).toBeVisible()
})

test('Given transferred weights awaiting verification, Then model selection remains unavailable', async () => {
  mockApi({ 'GET /models': { items: [luna, { ...local, installation: { ...installation, state: 'verifying', weights_present: true, completed_bytes: installation.download_bytes, job_id: job.id } }] }, 'GET /settings': defaults })
  renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByText('Preparing model')).toBeVisible()
  expect(screen.getByRole('radio', { name: local.display_name })).toBeDisabled()
  expect(within(row).queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument()
})

test('Given default local weights, When deletion is confirmed, Then Settings preserves the saved default', async () => {
  let model: Model = { ...local, status: 'available', unavailable_reason: null, installation: { ...installation, state: 'ready', weights_present: true } }
  const localDefaults = { default_model: local.key, reasoning_effort: 'default' }
  const { calls, fetchMock } = mockApi({
    'GET /models': () => json({ items: [luna, model] }), 'GET /settings': localDefaults,
    [`DELETE /models/${local.key}/installation`]: () => { model = local; return json({ ...job, kind: 'model_delete', state: 'completed' }, 202) },
  })
  const { user } = renderApp('/settings')
  await user.click(await screen.findByRole('button', { name: `Delete ${local.display_name} weights` }))
  const dialog = await screen.findByRole('alertdialog')
  expect(dialog).toHaveTextContent(/saved default/)
  expect(dialog).toHaveTextContent(/conversations and summaries/)
  await user.click(within(dialog).getByRole('button', { name: 'Delete weights' }))
  await waitFor(() => expect(screen.getByRole('radio', { name: local.display_name })).toBeChecked())
  expect(screen.getByRole('radio', { name: local.display_name })).toBeDisabled()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
  const deletion = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
  expect(new Headers(deletion?.[1]?.headers).get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/)
})

test('Given a failed download, When retry fails, Then its safe error is shown inline', async () => {
  mockApi({
    'GET /models': { items: [luna, { ...local, installation: { ...installation, state: 'failed', job_id: job.id, error: { code: 'MODEL_DOWNLOAD_FAILED', message: 'Download stopped. Try again.' } } }] }, 'GET /settings': defaults,
    [`POST /jobs/${job.id}/retry`]: () => json({ code: 'MODEL_RUNTIME_UNAVAILABLE', message: 'Ollama is unavailable. Check its service and retry.' }, 503),
  })
  const { user } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  await user.click(within(row).getByRole('button', { name: `Retry ${local.display_name} download` }))
  expect(await within(row).findByRole('alert')).toHaveTextContent(/Ollama is unavailable/)
})

test('Given installed weights requiring preparation, When Settings polls readiness, Then selection enables without a maintenance action', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let model = stale
  const { calls } = mockApi({ 'GET /models': () => json({ items: [luna, model] }), 'GET /settings': defaults })
  const { client, unmount } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).queryByRole('button', { name: /Verify/ })).not.toBeInTheDocument()
  expect(within(row).getByText('Preparing model')).toBeVisible()
  expect(within(row).getByText(/automatically/i, { selector: 'p' })).toBeVisible()
  expect(within(row).queryByRole('progressbar')).not.toBeInTheDocument()
  expect(screen.getByRole('radio', { name: local.display_name })).toBeDisabled()
  model = { ...local, status: 'available', unavailable_reason: null, unavailable_code: null, installation: { ...installation, state: 'ready', weights_present: true } }
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  await waitFor(() => expect(screen.getByRole('radio', { name: local.display_name })).toBeEnabled())
  expect(within(row).getByRole('status')).toHaveTextContent('Installed')
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
  unmount()
  client.clear()
})

test('Given queued preparation of retained weights, Then Settings shows background readiness without download controls or byte progress', async () => {
  const verifyingInstallation: ModelInstallation = { ...installation, state: 'queued', weights_present: true, job_id: job.id, completed_bytes: installation.download_bytes, operation: 'verify' }
  mockApi({ 'GET /models': { items: [luna, { ...local, installation: verifyingInstallation }] }, 'GET /settings': defaults })
  renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByText('Preparing model')).toBeVisible()
  expect(within(row).getByText(/Waiting to check model readiness/, { selector: 'p' })).toBeVisible()
  expect(within(row).getByText(/continues.*leave Settings/)).toBeVisible()
  expect(within(row).queryByRole('button', { name: /Pause/ })).not.toBeInTheDocument()
  expect(within(row).queryByRole('button', { name: /Verify|Retry/ })).not.toBeInTheDocument()
  expect(within(row).queryByRole('progressbar')).not.toBeInTheDocument()
  expect(within(row).queryByText(/ of .*GB/)).not.toBeInTheDocument()
  expect(screen.getByRole('radio', { name: local.display_name })).toBeDisabled()
})

test('Given active verification, Then the live status announces preparation and the transfer bar is absent', async () => {
  const verifyingInstallation: ModelInstallation = { ...installation, state: 'verifying', weights_present: true, job_id: job.id, completed_bytes: installation.download_bytes, operation: 'verify' }
  mockApi({ 'GET /models': { items: [luna, { ...local, installation: verifyingInstallation }] }, 'GET /settings': defaults })
  renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByRole('status')).toHaveTextContent('Preparing model')
  expect(within(row).getByText(/Checking model readiness/, { selector: 'p' })).toBeVisible()
  expect(within(row).queryByRole('progressbar')).not.toBeInTheDocument()
  expect(within(row).queryByRole('button', { name: /Pause|Verify|Retry/ })).not.toBeInTheDocument()
})

test('Given queued preparation, When verification starts, Then the persistent live status announces the new readiness phase', async () => {
  const preparingInstallation: ModelInstallation = { ...installation, state: 'queued', weights_present: true, job_id: job.id, operation: 'verify' }
  let model: Model = { ...local, installation: preparingInstallation }
  mockApi({ 'GET /models': () => json({ items: [luna, model] }), 'GET /settings': defaults })
  const { client } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  const status = within(row).getByRole('status')
  expect(status).toHaveTextContent('Waiting to check model readiness')
  model = { ...local, installation: { ...preparingInstallation, state: 'verifying' } }
  await client.invalidateQueries({ queryKey: queryKeys.models })
  await waitFor(() => expect(status).toHaveTextContent('Checking model readiness'))
  expect(status).toHaveTextContent('Preparing model')
})

test('Given preparation failed, When retried, Then the recovery action names preparation and uses the failed durable job', async () => {
  const failedInstallation: ModelInstallation = { ...installation, state: 'failed', weights_present: true, job_id: job.id, operation: 'verify', error: { code: 'LOCAL_MODEL_VERIFICATION_FAILED', message: 'Model preparation failed. Retry preparation.' } }
  const { calls } = mockApi({
    'GET /models': { items: [luna, { ...local, installation: failedInstallation }] }, 'GET /settings': defaults,
    [`POST /jobs/${job.id}/retry`]: { ...job, stage: 'verifying' },
  })
  const { user } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByText('Preparation failed')).toBeVisible()
  expect(within(row).getByRole('alert')).toHaveTextContent('Model preparation failed')
  expect(within(row).queryByRole('button', { name: /Verify/ })).not.toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: `Retry ${local.display_name} preparation` }))
  expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([`/jobs/${job.id}/retry`])
})

test('Given verification found missing weights, When Download is chosen, Then a new explicit download starts without retrying verification', async () => {
  const failedInstallation: ModelInstallation = { ...installation, state: 'failed', weights_present: false, job_id: job.id, operation: 'verify', error: { code: 'MODEL_WEIGHTS_MISSING', message: 'Model weights are missing. Download them again to use this model.' } }
  const { calls } = mockApi({
    'GET /models': { items: [luna, { ...local, installation: failedInstallation }] }, 'GET /settings': defaults,
    [`POST /models/${local.key}/download`]: { ...job, id: 'new-download-job' },
  })
  const { user } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument()
  expect(within(row).getByRole('alert')).toHaveTextContent('Model weights are missing')
  await user.click(within(row).getByRole('button', { name: `Download ${local.display_name}` }))
  expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([`/models/${local.key}/download`])
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ request_id: expect.any(String) })
})

test('Given deletion failed, When retried, Then the recovery action names deletion and retries its owning job without downloading', async () => {
  const failedInstallation: ModelInstallation = { ...installation, state: 'failed', weights_present: true, job_id: job.id, operation: 'delete', error: { code: 'LOCAL_MODEL_DELETE_FAILED', message: 'Could not delete model weights. Retry deletion.' } }
  const { calls } = mockApi({
    'GET /models': { items: [luna, { ...local, installation: failedInstallation }] }, 'GET /settings': defaults,
    [`POST /jobs/${job.id}/retry`]: { ...job, kind: 'model_delete', stage: 'deleting' },
  })
  const { user } = renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  const retry = within(row).getByRole('button', { name: `Retry ${local.display_name} deletion` })
  expect(retry).toHaveTextContent('Retry deletion')
  await user.click(retry)
  expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([`/jobs/${job.id}/retry`])
})

test('Given retained weights and an offline runtime, Then Settings explains the unavailable service without claiming preparation is running', async () => {
  mockApi({ 'GET /models': { items: [luna, { ...stale, unavailable_code: 'LOCAL_RUNTIME_UNAVAILABLE', unavailable_reason: 'The local model runtime is unavailable.' }] }, 'GET /settings': defaults })
  renderApp('/settings')
  const row = await screen.findByRole('region', { name: `Manage ${local.display_name}` })
  expect(within(row).getByRole('alert')).toHaveTextContent('The local model runtime is unavailable')
  expect(within(row).queryByText('Preparing model')).not.toBeInTheDocument()
  expect(within(row).queryByRole('button', { name: /Verify/ })).not.toBeInTheDocument()
  expect(screen.getByRole('radio', { name: local.display_name })).toBeDisabled()
})
