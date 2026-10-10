import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// The picker's citation line is muted text on a white popover, and on the highlighted row's muted ground. WCAG 2.2 AA
// asks 4.5:1 for small text. Achromatic oklch colours have linear luminance L^3; alpha mixes in sRGB.
const css = readFileSync(resolve(__dirname, '../../index.css'), 'utf8')
function tokens(selector: string) {
  const block = css.slice(css.indexOf(`${selector} {`)).split('}')[0]!
  return (name: string) => Number(new RegExp(`--${name}: oklch\\(([\\d.]+) 0 0\\)`).exec(block)![1])
}
const luminance = (lightness: number) => lightness ** 3
const toSrgb = (y: number) => (y <= 0.0031308 ? 12.92 * y : 1.055 * y ** (1 / 2.4) - 0.055)
const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const over = (fg: number, alpha: number, bg: number) => toLinear(alpha * toSrgb(fg) + (1 - alpha) * toSrgb(bg))
const contrast = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)

test.each([':root', '.dark'])('Given the %s theme, Then the citation line reaches 4.5:1 on plain and highlighted rows', (selector) => {
  const token = tokens(selector)
  const popover = luminance(token('popover'))
  const highlighted = luminance(token('muted'))
  expect(contrast(luminance(token('muted-foreground')), popover)).toBeGreaterThanOrEqual(4.5)
  // Highlighted rows use foreground at 70% (PaperCitation), since muted text on the light muted ground is 4.34:1.
  expect(contrast(over(luminance(token('foreground')), 0.7, highlighted), highlighted)).toBeGreaterThanOrEqual(4.5)
})

test('Given the light highlighted row, Then plain muted text would miss 4.5:1, which is why it darkens', () => {
  const token = tokens(':root')
  expect(contrast(luminance(token('muted-foreground')), luminance(token('muted')))).toBeLessThan(4.5)
})
