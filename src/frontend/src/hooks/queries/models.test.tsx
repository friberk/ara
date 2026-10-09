import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { Model } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { modelSupports, useModels } from './models'

afterEach(() => { focusManager.setFocused(undefined); vi.useRealTimers(); vi.unstubAllGlobals() })

test('Given the application disables general focus refresh, When focus returns, Then model readiness still refreshes', async () => {
  focusManager.setFocused(false)
  const { fetchMock } = mockApi({ 'GET /models': { items: [] } })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
  const { result, unmount } = renderHook(() => useModels(), { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(fetchMock).toHaveBeenCalledTimes(1)
  focusManager.setFocused(true)
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  unmount()
  client.clear()
})

test.each(['ready', 'queued', 'verifying'] as const)('Given %s local weights pending automatic readiness, When two seconds pass, Then fresh availability is retrieved and idle polling slows', async (state) => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  focusManager.setFocused(true)
  let model: Model = {
    kind: 'chat', key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B',
    status: 'unavailable', reasoning_efforts: ['default'], supports_streaming: true, supports_structured_output: true, context_window: 8192,
    unavailable_code: state === 'ready' ? 'LOCAL_MODEL_REVALIDATION_REQUIRED' : 'LOCAL_MODEL_NOT_READY',
    installation: { state, weights_present: true, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 5592218900, total_bytes: 5592218900, job_id: state === 'ready' ? null : 'b24b9f87-6035-4f72-b5f8-850d10d9fc57', digest: null, updated_at: null, error: null },
  }
  mockApi({ 'GET /models': () => json({ items: [model] }) })
  function Availability() {
    const models = useModels()
    return <output aria-label="Model availability">{models.isPending ? 'Loading' : modelSupports(models.data?.items[0], 'chat') ? 'Available' : 'Unavailable'}</output>
  }
  const { client, unmount, findByText, getByLabelText } = renderWithProviders(<Availability />)
  await findByText('Unavailable')
  model = { ...model, status: 'available', unavailable_code: null, installation: { ...model.installation!, state: 'ready', job_id: null } }
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  await findByText('Available')
  model = { ...model, status: 'unavailable', unavailable_code: 'OLLAMA_UNAVAILABLE' }
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(getByLabelText('Model availability')).toHaveTextContent('Available')
  await act(async () => { await vi.advanceTimersByTimeAsync(28_000) })
  await findByText('Unavailable')
  unmount()
  client.clear()
})
