import { formatTokens, formatUsd, usedShare } from './usage-format'

test('Given token counts, Then they read as compact thousands and millions', () => {
  expect([0, 950, 1000, 12_400, 64_000, 3_072, 1_050_000, 1_000_000].map(formatTokens)).toEqual(['0', '950', '1k', '12.4k', '64k', '3.1k', '1.05M', '1M'])
})

test('Given decimal dollar strings, Then they read as short currency without hiding small spend', () => {
  expect(['0.00000000', '0.01230000', '0.00000900', '1.23456000', '12.00000000'].map(formatUsd)).toEqual(['$0.00', '$0.0123', '<$0.0001', '$1.23', '$12.00'])
})

test('Given used and budget, Then the share is a whole percent, the ring clamps at full', () => {
  expect(usedShare(null, 64_000)).toEqual({ percent: 0, fraction: 0 })
  expect(usedShare(12_400, 64_000)).toEqual({ percent: 19, fraction: 12_400 / 64_000 })
  expect(usedShare(90_000, 64_000)).toEqual({ percent: 141, fraction: 1 })
  expect(usedShare(10, 0)).toEqual({ percent: 0, fraction: 0 })
})
