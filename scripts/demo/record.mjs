// Records every demo clip in order against the isolated ara-demo stack (ARA-113).
// Usage: node record.mjs [--reset] [--run <id>] [--only 01,05] [--headed] [--skip-warmup]
// --reset empties the ara-demo stack first; a full take always starts from an empty app.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { chromium } from 'playwright'

import { waitIdle } from './lib/api.mjs'
import { APP, OUT, PAPERS, VIEWPORT, runId } from './lib/config.mjs'
import { Stage } from './lib/stage.mjs'
import { clips } from './clips/index.mjs'

const { values } = parseArgs({
  options: {
    reset: { type: 'boolean', default: false },
    run: { type: 'string' },
    only: { type: 'string' },
    headed: { type: 'boolean', default: false },
    'skip-warmup': { type: 'boolean', default: false },
  },
})

const run = values.run ?? runId()
const runDir = path.join(OUT, run)
const rawDir = path.join(runDir, 'raw')
const timelinePath = path.join(runDir, 'timeline.json')
fs.mkdirSync(rawDir, { recursive: true })

const wanted = values.only ? new Set(values.only.split(',').map((s) => s.trim().padStart(2, '0'))) : null
const selected = clips.filter((clip) => !wanted || wanted.has(clip.id.slice(0, 2)))
if (selected.length === 0) throw new Error(`no clips match --only ${values.only}`)
for (const paper of Object.values(PAPERS)) {
  if (paper.file && !fs.existsSync(paper.file)) throw new Error(`missing input ${paper.file} (see scripts/demo/README.md)`)
}

const timeline = fs.existsSync(timelinePath) ? JSON.parse(fs.readFileSync(timelinePath, 'utf8')) : { run, clips: {} }
const save = () => fs.writeFileSync(timelinePath, `${JSON.stringify(timeline, null, 2)}\n`)

// Every route and the PDF viewer load lazily; the dev server compiles them on first use. Visiting them
// off camera keeps compile pauses and dependency reloads out of the clips.
async function warmup(browser) {
  console.log('warming up the dev server')
  const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: 'light' })
  const page = await context.newPage()
  const visit = async (pathname) => {
    await page.goto(`${APP}${pathname}`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
  }
  // Deep-linked searches are not saved to the search history.
  await visit('/search?q=warm&provider=openalex')
  await visit('/library')
  await visit('/papers/00000000-0000-0000-0000-000000000000')
  await visit('/?settings=general')
  await visit('/')
  await page.keyboard.press('ControlOrMeta+k')
  await page.waitForTimeout(1500)
  await page.evaluate(() => import('/src/features/workspace/PdfViewer.tsx'))
  await page.waitForTimeout(1500)
  await context.close()
}

const stack = (command) =>
  execFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'stack.sh'), [command], { stdio: 'inherit' })
if (values.reset) stack('reset')

const browser = await chromium.launch({ headless: !values.headed })
const ctx = {}
try {
  if (!values['skip-warmup']) await warmup(browser)
  for (const clip of selected) {
    console.log(`\n${clip.id}`)
    await waitIdle()
    if (clip.restart) {
      // Off camera: restart every service so the clip shows the library surviving a restart.
      console.log('  restarting the ara-demo stack')
      stack('restart')
      await warmup(browser)
    }
    const stage = await new Stage(browser, { id: clip.id, dir: rawDir }).open()
    try {
      await clip.run(stage, ctx)
    } catch (error) {
      await stage.abort(error)
      throw error
    }
    timeline.clips[clip.id] = await stage.finish()
    save()
    console.log(`  saved ${path.join(rawDir, timeline.clips[clip.id].video)}`)
  }
} finally {
  await browser.close()
}
console.log(`\ntimeline: ${timelinePath}`)
