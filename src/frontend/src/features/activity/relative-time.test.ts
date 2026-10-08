import { act, renderHook } from '@testing-library/react'
import { relativeTime, useNow } from './relative-time'

const now = Date.parse('2026-10-08T12:00:00Z')
afterEach(() => vi.useRealTimers())

test('Given timestamps relative to a fixed now, Then labels read naturally from just now to years', () => {
  expect(relativeTime('2026-10-08T11:59:30Z', now)).toBe('just now')
  expect(relativeTime('2026-10-08T11:55:00Z', now)).toBe('5 minutes ago')
  expect(relativeTime('2026-10-08T10:00:00Z', now)).toBe('2 hours ago')
  expect(relativeTime('2026-10-07T12:00:00Z', now)).toBe('yesterday')
  expect(relativeTime('2026-10-05T12:00:00Z', now)).toBe('3 days ago')
  expect(relativeTime('2026-10-01T12:00:00Z', now)).toBe('last week')
  expect(relativeTime('2025-10-07T12:00:00Z', now)).toBe('last year')
})

test('Given a missing or unreadable timestamp, Then no label is produced', () => {
  expect(relativeTime(null, now)).toBeNull()
  expect(relativeTime(undefined, now)).toBeNull()
  expect(relativeTime('not a date', now)).toBeNull()
})

test('Given an idle page, Then the current time refreshes on its interval', () => {
  vi.useFakeTimers()
  vi.setSystemTime(now)
  const { result } = renderHook(() => useNow(30_000))
  expect(result.current).toBe(now)
  act(() => { vi.advanceTimersByTime(30_000) })
  expect(result.current).toBe(now + 30_000)
})
