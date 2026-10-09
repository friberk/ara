import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { mockApi } from '@/test/fetch-routes'
import { useModels } from './models'

afterEach(() => { focusManager.setFocused(undefined); vi.unstubAllGlobals() })

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
