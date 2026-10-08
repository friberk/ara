// jsdom computes no styles and Vitest stubs CSS imports (even ?raw) to empty, so these read the reader's stylesheet
// from disk as text. The browser check compares the rendered mark in both themes.
import { readFileSync } from 'node:fs'

const css = readFileSync(`${import.meta.dirname}/pdf-viewer.css`, 'utf8')

test('Given the stylesheet, Then it is read whole', () => {
  expect(css).toMatch(/\.pdf-viewer \.textLayer/)
})

test('Given either theme, Then the evidence mark uses one fixed colour, because PDF pages stay white paper in both', () => {
  expect(css).not.toMatch(/\.dark\b/)
  expect(css).not.toMatch(/var\(--evidence\)/)
})

test('Given a strong mark that just landed, Then it pulses; context lines never pulse', () => {
  expect(css).toMatch(/\[data-citation-pulse\][^{]*\{[^}]*animation:\s*citation-pulse/)
  expect(css).not.toMatch(/\[data-citation-highlight='pulse'\]/)
})
