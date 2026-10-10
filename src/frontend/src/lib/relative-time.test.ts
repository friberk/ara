import { renderHook, act } from '@testing-library/react'
import { compactRelativeTime, fullDateTime, longRelativeTime, useNow } from './relative-time'

// Local noon, so calendar dates and years do not depend on the machine's time zone.
const now = new Date(2026, 9, 10, 12, 0, 0).getTime()
const ago = (seconds: number) => new Date(now - seconds * 1000).toISOString()
const minute = 60
const hour = 3600
const day = 86_400

test.each([
  [0, 'now'], [59, 'now'], [60, '1m'], [12 * minute, '12m'], [59 * minute + 59, '59m'], [hour, '1h'], [3 * hour, '3h'], [23 * hour + 59 * minute, '23h'],
  [day, '1d'], [2 * day, '2d'], [6 * day + 23 * hour, '6d'],
])('Given an activity %s seconds ago, Then the compact label is %s', (seconds, label) => {
  expect(compactRelativeTime(ago(seconds), now)).toBe(label)
})

test('Given an activity a week or more ago, Then the compact label is the date, with the year only for earlier years', () => {
  expect(compactRelativeTime(ago(7 * day), now)).toBe('Oct 3')
  expect(compactRelativeTime(new Date(2026, 0, 2, 9).toISOString(), now)).toBe('Jan 2')
  expect(compactRelativeTime(new Date(2025, 9, 2, 9).toISOString(), now)).toBe('Oct 2, 2025')
})

test('Given a timestamp slightly in the future from clock skew, Then it reads as now', () => {
  expect(compactRelativeTime(ago(-30), now)).toBe('now')
})

test.each([
  [10, 'just now'], [60, '1 minute ago'], [12 * minute, '12 minutes ago'], [hour, '1 hour ago'], [3 * hour, '3 hours ago'], [day, '1 day ago'], [3 * day, '3 days ago'], [6 * day, '6 days ago'],
])('Given an activity %s seconds ago, Then screen readers hear %s', (seconds, label) => {
  expect(longRelativeTime(ago(seconds), now)).toBe(label)
})

test('Given an activity a week or more ago, Then the long form is the written date', () => {
  expect(longRelativeTime(ago(7 * day), now)).toBe('October 3')
  expect(longRelativeTime(new Date(2025, 9, 2, 9).toISOString(), now)).toBe('October 2, 2025')
})

test('Given an unreadable or missing timestamp, Then every form is empty', () => {
  expect(compactRelativeTime('not a date', now)).toBeNull()
  expect(longRelativeTime(undefined, now)).toBeNull()
  expect(fullDateTime('nope')).toBeNull()
})

test('Given a timestamp, Then the full form carries the local date and time', () => {
  expect(fullDateTime(new Date(2025, 9, 2, 14, 5).toISOString())).toMatch(/October 2, 2025.*2:05\s?PM/)
})

test('Given the hook is mounted, When the interval passes, Then the time moves on', () => {
  vi.useFakeTimers()
  const { result } = renderHook(() => useNow(1000))
  const first = result.current
  act(() => { vi.advanceTimersByTime(1000) })
  expect(result.current).toBeGreaterThan(first)
  vi.useRealTimers()
})
