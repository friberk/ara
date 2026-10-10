// Test-after coverage (ARA-036 TDD audit), confirmed by breaking each branch and watching the test fail.
import { effortText } from './format'

test('Given each reasoning effort, Then the label reads as a phrase', () => {
  expect(effortText('none')).toBe('No reasoning')
  expect(effortText('low')).toBe('Low reasoning')
  expect(effortText('xhigh')).toBe('Extra high reasoning')
  expect(effortText('custom')).toBe('custom reasoning')
  expect(effortText('default')).toBe('Runtime preset')
  expect(effortText('on')).toBe('Reasoning enabled')
})
