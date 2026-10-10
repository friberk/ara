import { act, renderHook } from '@testing-library/react'
import { useNow } from './use-now'

afterEach(() => vi.useRealTimers())

test('Given an idle page, Then the current time refreshes on its interval', () => {
  const start = Date.parse('2026-10-08T12:00:00Z')
  vi.useFakeTimers()
  vi.setSystemTime(start)
  const { result } = renderHook(() => useNow(30_000))
  expect(result.current).toBe(start)
  act(() => { vi.advanceTimersByTime(30_000) })
  expect(result.current).toBe(start + 30_000)
})
