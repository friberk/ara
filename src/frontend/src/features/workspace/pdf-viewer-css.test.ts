// jsdom computes no styles and Vitest stubs CSS imports (even ?raw) to empty, so these read the reader's stylesheet
// from disk as text. The browser check compares the rendered mark in both themes.
import { readFileSync } from 'node:fs'

const css = readFileSync(`${import.meta.dirname}/pdf-viewer.css`, 'utf8')

test('Given the stylesheet, Then it is read whole', () => {
  expect(css).toMatch(/\.pdf-viewer \.textLayer/)
})

const tokens = readFileSync(`${import.meta.dirname}/../../index.css`, 'utf8')
const darkBlock = tokens.slice(tokens.indexOf('.dark {'), tokens.indexOf('}', tokens.indexOf('.dark {')))

test('Given either theme, Then the evidence mark uses one fixed colour, because PDF pages stay white paper in both', () => {
  expect(css).not.toMatch(/\.dark\b/)
  // One source of truth: the reader reads the design token, and the token has a single value in both themes.
  expect(css).toMatch(/var\(--evidence\)/)
  expect(css).not.toMatch(/oklch\(0\.93 0\.13 96/)
  expect(darkBlock).not.toMatch(/--evidence:/)
})

test('Given a strong mark that just landed, Then it pulses; context lines never pulse', () => {
  expect(css).toMatch(/\[data-citation-pulse\][^{]*\{[^}]*animation:\s*citation-pulse/)
  expect(css).not.toMatch(/\[data-citation-highlight='pulse'\]/)
})

// ARA-089: the first design left context lines untinted because a background tint on the 3,200-character chunk
// washed the page in stripes. They now get only a thin dotted underline (text-decoration, not a background), so the
// excerpt's extent is visible without competing with the strong lines.
test('Given context lines, Then they carry a thin dotted underline and no background tint', () => {
  expect(css).not.toMatch(/\.textLayer \[data-citation-highlight\][^{]*\{[^}]*background/)
  expect(css).toMatch(/\[data-citation-highlight='context'\]\s*\{[^}]*text-decoration:\s*underline dotted[^;]*var\(--pdf-evidence-edge\)/)
})

test('Given a strong mark, Then it is the full evidence tint with an edge line, not a faded mix', () => {
  const strong = css.match(/\[data-citation-highlight='strong'\]\s*\{[^}]*\}/)?.[0] ?? ''
  expect(strong).toMatch(/background-color:\s*var\(--pdf-evidence\)/)
  expect(strong).not.toMatch(/color-mix/)
  expect(strong).toMatch(/box-shadow:\s*inset 0 -2px 0 var\(--pdf-evidence-edge\)/)
})

test('Given the edge colour, Then it is one token with one value in both themes, dark enough for 3:1 on white paper', () => {
  expect(css).toMatch(/--pdf-evidence-edge:\s*var\(--evidence-edge\)/)
  expect(tokens).toMatch(/^\s*--evidence-edge:\s*oklch\(0\.[3-6]\d*/m)
  expect(darkBlock).not.toMatch(/--evidence-edge:/)
})

test('Given a cited region from stored boxes, Then it is an outlined translucent box that pulses once and respects reduced motion', () => {
  expect(css).toMatch(/\[data-citation-region\]\s*\{[^}]*border:\s*2px solid var\(--pdf-evidence-edge\)/)
  expect(css).toMatch(/\[data-citation-region\]\s*\{[^}]*background-color:\s*color-mix\(in oklch, var\(--pdf-evidence\)/)
  expect(css).toMatch(/\[data-citation-region\]\[data-citation-pulse\][^{]*\{[^}]*animation:\s*citation-pulse/)
  const reduced = css.slice(css.indexOf('prefers-reduced-motion'), css.indexOf('forced-colors'))
  expect(reduced).toMatch(/\[data-citation-region\]\[data-citation-pulse\]/)
  expect(css.slice(css.indexOf('forced-colors'))).toMatch(/\[data-citation-region\]/)
})

// Character-precise marks are <mark> elements inside the transparent text-layer spans; the browser's own mark
// colours would paint the hidden text black on yellow over the canvas.
test('Given a mark inside a text-layer span, Then its text stays transparent and only the evidence tint shows', () => {
  expect(css).toMatch(/\.textLayer mark\s*\{[^}]*color:\s*transparent/)
  expect(css).toMatch(/\.textLayer mark\s*\{[^}]*background(?:-color)?:\s*(?:none|transparent)/)
})
