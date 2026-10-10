import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

import { REPO } from './config.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)
const template = fs.readFileSync(path.join(here, '../card.html'), 'utf8')
const wordmark = fs.readFileSync(path.join(REPO, 'branding/ara-wordmark.svg'), 'utf8')

const font = (pkg, file) =>
  fs.readFileSync(path.join(path.dirname(require.resolve(`${pkg}/package.json`)), 'files', file)).toString('base64')
const fontFaces = `<style>
@font-face { font-family: "Geist Variable"; font-weight: 100 900; src: url(data:font/woff2;base64,${font('@fontsource-variable/geist', 'geist-latin-wght-normal.woff2')}) format("woff2"); }
@font-face { font-family: "Geist Mono Variable"; font-weight: 100 900; src: url(data:font/woff2;base64,${font('@fontsource-variable/geist-mono', 'geist-mono-latin-wght-normal.woff2')}) format("woff2"); }
</style>`
const html = template.replace('</head>', `${fontFaces}</head>`)

const esc = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const mark = (className) => `<div class="wordmark ${className}" role="img" aria-label="ara.">${wordmark}</div>`

function featureCard({ step, total, title, subtitle }) {
  return `<div class="stage"><div class="stack">
    <p class="step">${String(step).padStart(2, '0')} / ${String(total).padStart(2, '0')}</p>
    <h1 class="title">${esc(title)}</h1>
    <p class="subtitle">${esc(subtitle)}</p>
  </div>${mark('corner')}</div>`
}

function heroCard({ name, line }) {
  return `<div class="stage hero"><div class="stack">
    ${mark('')}
    <p class="name">${esc(name)}</p>
    ${line ? `<p class="line">${esc(line)}</p>` : ''}
  </div></div>`
}

const fastForward =
  '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M1.5 3.2v9.6L8 8 1.5 3.2Zm6.8 0v9.6L14.8 8 8.3 3.2Z"/></svg>'

// Renders every card PNG (1920x1080) and the "sped up" badge PNGs for the given factors.
export async function render({ cards, clipIds, factors = [], cardsDir, badgesDir }) {
  fs.mkdirSync(cardsDir, { recursive: true })
  fs.mkdirSync(badgesDir, { recursive: true })
  const browser = await chromium.launch()
  const written = { cards: {}, badges: {} }
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
    await page.setContent(html, { waitUntil: 'load' })
    await page.evaluate(() => document.fonts.ready)
    const shoot = async (markup, file) => {
      await page.evaluate((inner) => {
        document.getElementById('root').innerHTML = inner
      }, markup)
      await page.evaluate(() => document.fonts.ready)
      await page.screenshot({ path: file })
      return file
    }

    written.cards.opening = await shoot(heroCard(cards.opening), path.join(cardsDir, '00-opening.png'))
    clipIds.forEach((id) => {
      if (!cards.clips[id]) throw new Error(`cards.json has no card for ${id}`)
    })
    for (const [index, id] of clipIds.entries()) {
      const card = cards.clips[id]
      written.cards[id] = await shoot(
        featureCard({ step: index + 1, total: clipIds.length, ...card }),
        path.join(cardsDir, `${id}.png`),
      )
    }
    written.cards.closing = await shoot(heroCard(cards.closing), path.join(cardsDir, '99-closing.png'))

    for (const factor of factors) {
      await page.evaluate(
        ({ icon, text }) => {
          document.getElementById('root').innerHTML =
            `<div class="badge-host"><span class="badge">${icon}<span>${text}</span></span></div>`
        },
        { icon: fastForward, text: `Sped up ${factor}×` },
      )
      const file = path.join(badgesDir, `badge-${factor}x.png`)
      await page.locator('.badge').screenshot({ path: file, omitBackground: true })
      written.badges[factor] = file
    }
  } finally {
    await browser.close()
  }
  return written
}

// Width and height from a PNG's IHDR chunk.
export function pngSize(file) {
  const header = Buffer.alloc(24)
  const fd = fs.openSync(file, 'r')
  fs.readSync(fd, header, 0, 24, 0)
  fs.closeSync(fd)
  return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) }
}
