// Test-after coverage (ARA-036 TDD audit), confirmed by breaking each branch and watching the test fail.
import { effortText, formatTimestamp } from './format'

test('Given each reasoning effort, Then the label reads as a phrase', () => {
  expect(effortText('none')).toBe('No reasoning')
  expect(effortText('low')).toBe('Low reasoning')
  expect(effortText('xhigh')).toBe('Extra high reasoning')
  expect(effortText('custom')).toBe('custom reasoning')
})

test('Given an unreadable timestamp, Then it is shown as stored instead of "Invalid Date"', () => {
  expect(formatTimestamp('not-a-date')).toBe('not-a-date')
  expect(formatTimestamp('2026-10-08T12:00:00Z')).not.toBe('2026-10-08T12:00:00Z')
})
