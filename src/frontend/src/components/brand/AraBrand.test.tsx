import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render } from '@testing-library/react'
import { AraMark, AraWordmark } from './AraBrand'

const pathOf = (file: string) => /\sd="([^"]+)"/.exec(readFileSync(resolve(__dirname, '../../../../../branding', file), 'utf8'))![1]
const viewBoxOf = (file: string) => /viewBox="([^"]+)"/.exec(readFileSync(resolve(__dirname, '../../../../../branding', file), 'utf8'))![1]

test.each([
  ['ara-wordmark.svg', AraWordmark],
  ['ara-mark.svg', AraMark],
])('Given %s, Then the inlined component matches its generated path and viewBox', (file, Component) => {
  const { container } = render(<Component />)
  expect(container.querySelector('path')?.getAttribute('d')).toBe(pathOf(file))
  expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe(viewBoxOf(file))
})
