// Renders branding/favicon.svg to the PNG fallbacks in src/frontend/public/ with the frontend's Playwright.
// Usage (after `npm ci` in src/frontend): node branding/render_icons.mjs
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from '../src/frontend/node_modules/playwright/index.mjs'

const here = (path) => fileURLToPath(new URL(path, import.meta.url))
const svg = readFileSync(here('favicon.svg'), 'utf8')
// iOS and Android apply their own mask, so the touch icon is an opaque square without the rounded corners.
const icons = [
  { file: 'favicon-32.png', size: 32, svg },
  { file: 'apple-touch-icon.png', size: 180, svg: svg.replace(' rx="14"', '') },
]

const browser = await chromium.launch()
const page = await browser.newPage({ colorScheme: 'light' })
for (const icon of icons) {
  await page.setViewportSize({ width: icon.size, height: icon.size })
  await page.setContent(`<style>html,body{margin:0}svg{display:block;width:${icon.size}px;height:${icon.size}px}</style>${icon.svg}`)
  writeFileSync(here(`../src/frontend/public/${icon.file}`), await page.screenshot({ clip: { x: 0, y: 0, width: icon.size, height: icon.size }, omitBackground: true }))
}
await browser.close()
