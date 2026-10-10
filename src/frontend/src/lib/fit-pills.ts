/**
 * How many pills fit on one line of `available` pixels, with `gap` between them. When they all fit there is no "+N" pill;
 * otherwise the line also holds one `plusWidth` wide. At least one pill always shows.
 */
export function fitPills(widths: readonly number[], available: number, plusWidth: number, gap: number) {
  if (!widths.length) return 0
  const all = widths.reduce((sum, width) => sum + width, 0) + gap * (widths.length - 1)
  if (all <= available) return widths.length
  let used = 0
  let count = 0
  for (const width of widths) {
    const next = used + (count ? gap : 0) + width
    if (next + gap + plusWidth > available) break
    used = next
    count++
  }
  return Math.max(count, 1)
}
