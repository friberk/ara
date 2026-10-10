/** Compact token counts: 950, 12.4k, 64k, 1.05M. */
export function formatTokens(count: number): string {
  const trim = (value: number, digits: number) => String(Number(value.toFixed(digits)))
  if (count >= 1_000_000) return `${trim(count / 1_000_000, 2)}M`
  if (count >= 1000) return `${trim(count / 1000, 1)}k`
  return String(count)
}

/** A decimal dollar string from the API as short currency; spend under a hundredth of a cent is not shown as zero. */
export function formatUsd(amount: string): string {
  const value = Number(amount)
  if (!(value > 0)) return '$0.00'
  if (value < 0.0001) return '<$0.0001'
  return value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`
}

/** The share of the budget a turn sent: a whole percent for the label, a clamped fraction for the ring. */
export function usedShare(used: number | null, budget: number): { percent: number; fraction: number } {
  if (!used || budget <= 0) return { percent: 0, fraction: 0 }
  return { percent: Math.round((used / budget) * 100), fraction: Math.min(used / budget, 1) }
}
