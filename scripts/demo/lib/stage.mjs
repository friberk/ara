import fs from 'node:fs'
import path from 'node:path'
import { expect } from 'playwright/test'
import { recordPage } from 'testreel'

import { APP, FRAME, VIEWPORT } from './config.mjs'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// One recorded clip: a fresh browser context with testreel's cursor, window frame and background.
// Pointer actions go through the recorder so the cursor overlay follows them. Waits are logged so the
// assembly step can time-lapse them, and the first page load is trimmed off the head.
export class Stage {
  constructor(browser, { id, dir, log = console.log }) {
    this.browser = browser
    this.id = id
    this.dir = dir
    this.log = log
    this.lapses = []
    this.marks = {}
    this.start = 0
    this.nextFile = null
  }

  async open() {
    this.context = await this.browser.newContext({
      viewport: VIEWPORT,
      colorScheme: 'light',
      recordVideo: { dir: this.dir, size: VIEWPORT },
    })
    this.t0 = Date.now()
    this.page = await this.context.newPage()
    this.page.on('filechooser', async (chooser) => {
      if (!this.nextFile) throw new Error('a file chooser opened without a file prepared')
      await chooser.setFiles(this.nextFile)
      this.nextFile = null
    })
    this.recorder = await recordPage(this.page, {
      outputDir: this.dir,
      name: this.id,
      cursor: { style: 'default', size: 44, rippleColor: 'rgba(10, 10, 10, 0.28)', rippleSize: 90 },
      chrome: { titleBarHeight: FRAME.titleBar, titleBarColor: '#ececec', url: false },
      background: { color: FRAME.background, padding: FRAME.padding, borderRadius: 12 },
      speed: 1,
      outputFormat: 'mp4',
      videoStartedAt: this.t0,
    })
    return this
  }

  now() {
    return (Date.now() - this.t0) / 1000
  }

  mark(name) {
    this.marks[name] = this.now()
  }

  async go(pathname, ready) {
    await this.page.goto(`${APP}${pathname}`, { waitUntil: 'domcontentloaded' })
    await expect(ready).toBeVisible({ timeout: 60_000 })
    await this.page.waitForTimeout(500)
    this.start = this.now()
  }

  // Scrolls the element to the middle of its scrolling container when it isn't comfortably in view.
  // testreel clicks the element's centre without scrolling, and the app only scrolls inner regions.
  async smooth(locator) {
    await locator.waitFor({ state: 'visible', timeout: 30_000 })
    const moved = await locator.evaluate(
      (el) =>
        new Promise((resolve) => {
          const rect = el.getBoundingClientRect()
          if (rect.top >= 64 && rect.bottom <= window.innerHeight - 140) return resolve(false)
          el.scrollIntoView({ behavior: 'smooth', block: 'center' })
          let last = null
          let still = 0
          const started = performance.now()
          const tick = () => {
            const top = el.getBoundingClientRect().top
            still = last !== null && Math.abs(top - last) < 0.5 ? still + 1 : 0
            last = top
            if (still > 8 || performance.now() - started > 3000) resolve(true)
            else requestAnimationFrame(tick)
          }
          requestAnimationFrame(tick)
        }),
    )
    if (moved) await this.page.waitForTimeout(300)
  }

  async scrollBy(region, top) {
    await region.evaluate((el, by) => el.scrollBy({ top: by, behavior: 'smooth' }), top)
    await this.page.waitForTimeout(900)
  }

  async click(locator, options) {
    await this.smooth(locator)
    await this.recorder.click(locator, { timeout: 15_000, ...options })
  }

  async hover(locator, pauseMs = 0) {
    await this.smooth(locator)
    await this.recorder.hover(locator, { timeout: 15_000 })
    if (pauseMs) await this.page.waitForTimeout(pauseMs)
  }

  async type(locator, text, delay = 55) {
    await this.smooth(locator)
    await this.recorder.type(locator, text, { delay, timeout: 15_000 })
  }

  // Keys for the focused editor. The TipTap composer keeps pills, and recorder.type would click its centre first.
  async keys(text, delay = 50) {
    await this.page.keyboard.type(text, { delay })
    await this.page.waitForTimeout(300)
  }

  async press(key) {
    await this.recorder.keyboard(key)
  }

  async zoom(locator, scale = 1.6, holdMs = 2500) {
    await this.recorder.zoom({ selector: locator, scale, duration: 700 })
    await this.page.waitForTimeout(holdMs)
    await this.recorder.zoom({ scale: 1, duration: 700 })
  }

  async pause(ms) {
    await this.page.waitForTimeout(ms)
  }

  // Radix ignores Escape for one render after a menu or dialog opens, so retry until it closes.
  // A count check, because a menu and its submenu can both match.
  async escape(gone) {
    await expect(async () => {
      await this.page.keyboard.press('Escape')
      await expect(gone).toHaveCount(0, { timeout: 800 })
    }).toPass({ timeout: 8_000 })
  }

  prepareFile(file) {
    if (!fs.existsSync(file)) throw new Error(`missing input ${file}`)
    this.nextFile = file
  }

  // Runs a long wait and logs it for time-lapse. While it runs, the status text is sampled so each
  // new step label keeps a moment at normal speed.
  async lapse(label, wait, { status } = {}) {
    const start = this.now()
    const changes = []
    let last = null
    let polling = true
    const poll = (async () => {
      while (polling) {
        if (status) {
          const text = (await status.allInnerTexts().catch(() => [])).join(' | ').trim()
          if (text && text !== last) {
            if (last !== null) changes.push(this.now())
            last = text
          }
        }
        await sleep(250)
      }
    })()
    try {
      await wait()
    } finally {
      polling = false
      await poll
    }
    const end = this.now()
    this.lapses.push({ label, start, end, changes })
    this.log(`  ${label}: ${(end - start).toFixed(1)} s${changes.length ? `, ${changes.length} label change(s)` : ''}`)
  }

  async finish(holdMs = 1500) {
    await this.page.waitForTimeout(holdMs)
    const end = this.now()
    const result = await this.recorder.stop()
    if (!result.video || !result.video.endsWith('.mp4')) throw new Error(`testreel produced no mp4 for ${this.id}`)
    return {
      id: this.id,
      video: path.basename(result.video),
      start: Number(this.start.toFixed(3)),
      end: Number(end.toFixed(3)),
      lapses: this.lapses.map((l) => ({
        ...l,
        start: Number(l.start.toFixed(3)),
        end: Number(l.end.toFixed(3)),
        changes: l.changes.map((t) => Number(t.toFixed(3))),
      })),
      marks: this.marks,
    }
  }

  async abort(error) {
    const shot = path.join(this.dir, `${this.id}-failure.png`)
    await this.page.screenshot({ path: shot }).catch(() => {})
    await this.context.close().catch(() => {})
    await this.page.video()?.delete().catch(() => {})
    this.log(`  failed: ${error.message}\n  screenshot: ${shot}`)
  }
}
