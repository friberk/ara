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

// After the first browser round: a faint tint on the rest of the 3,200-character chunk still washed most of page 7
// in stripes, so context lines stay unmarked and the strong lines are the only mark on the page.
test('Given context lines, Then they carry no tint', () => {
  expect(css).not.toMatch(/\[data-citation-highlight='context'\][^{]*\{[^}]*background/)
  expect(css).not.toMatch(/\.textLayer \[data-citation-highlight\][^{]*\{[^}]*background/)
})

// Character-precise marks are <mark> elements inside the transparent text-layer spans; the browser's own mark
// colours would paint the hidden text black on yellow over the canvas.
test('Given a mark inside a text-layer span, Then its text stays transparent and only the evidence tint shows', () => {
  expect(css).toMatch(/\.textLayer mark\s*\{[^}]*color:\s*transparent/)
  expect(css).toMatch(/\.textLayer mark\s*\{[^}]*background(?:-color)?:\s*(?:none|transparent)/)
})
