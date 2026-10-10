import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const html = readFileSync(resolve(__dirname, '../../../index.html'), 'utf8')

test('Given index.html, Then the title is ara. and the favicon is the svg tile', () => {
  expect(html).toMatch(/<title>ara\.<\/title>/)
  expect(html).toContain('<link rel="icon" type="image/svg+xml" href="/favicon.svg" />')
  expect(html).not.toContain('Research Assistant')
  expect(readFileSync(resolve(__dirname, '../../../public/favicon.svg'), 'utf8')).toBe(readFileSync(resolve(__dirname, '../../../../../branding/favicon.svg'), 'utf8'))
})

test('Given index.html, Then PNG and apple-touch fallbacks are linked and present in public/', () => {
  expect(html).toContain('<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />')
  expect(html).toContain('<link rel="apple-touch-icon" href="/apple-touch-icon.png" />')
  for (const file of ['favicon-32.png', 'apple-touch-icon.png']) {
    expect(readFileSync(resolve(__dirname, '../../../public', file)).subarray(1, 4).toString()).toBe('PNG')
  }
})
