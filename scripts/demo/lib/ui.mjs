import { expect } from 'playwright/test'

// Role and label locators shared by the clips, following src/frontend/e2e/*.spec.ts.
const escapeRegex = (text) => text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')

export const home = (page) => page.getByRole('heading', { name: 'What are you researching?' })
export const card = (page, doi) =>
  page.getByRole('article').filter({ has: page.getByRole('link', { name: new RegExp(escapeRegex(doi)) }) })
export const reader = (page) => page.getByRole('region', { name: 'PDF reader', exact: true })
export const firstPage = (page) => page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas').first()
// Retrieval progress, then the active preparation step: each new label keeps a moment at normal speed.
export const readerStatus = (page) => reader(page).locator('[role="status"], li[aria-current="step"]')
export const summaryCard = (page) => page.getByRole('article', { name: 'Paper summary' })
export const summaryStage = (page) => summaryCard(page).locator('[aria-live="polite"] span.font-medium')
export const conversation = (page) => page.getByRole('region', { name: 'Conversation' })
export const answers = (page) => page.getByRole('article', { name: 'Assistant message' })
export const citationChip = /^Source, (?:.+, )?pages? \d+/
export const outcome = (page) =>
  page.getByRole('status').filter({ hasText: /cited passage on page|cited region on page|showing page/i })

export async function answerComplete(page) {
  await expect(page.getByRole('button', { name: 'Stop generation' })).toBeHidden({ timeout: 240_000 })
  await expect(answers(page).last()).toHaveAttribute('aria-busy', 'false', { timeout: 240_000 })
}

// The first chip citing page 3 or later, so the reader visibly jumps; otherwise the first chip.
export async function pickChip(chips, minPage = 3) {
  const count = await chips.count()
  if (count === 0) throw new Error('no citation chips')
  for (let i = 0; i < count; i++) {
    const label = (await chips.nth(i).getAttribute('aria-label')) ?? ''
    const pageNumber = Number(label.match(/pages? (\d+)/)?.[1])
    if (pageNumber >= minPage && (await chips.nth(i).isVisible())) return chips.nth(i)
  }
  return chips.first()
}

// Waits until a locator's text stops changing, e.g. a regenerated summary replacing the old one.
export async function settled(locator, { quietMs = 1500, timeoutMs = 30_000 } = {}) {
  const started = Date.now()
  let last = null
  let since = Date.now()
  while (Date.now() - started < timeoutMs) {
    const text = (await locator.allInnerTexts().catch(() => [])).join('\n')
    if (text !== last) {
      last = text
      since = Date.now()
    } else if (Date.now() - since >= quietMs) {
      return text
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error('content kept changing')
}

// Clicks a citation, then keeps the pointer on the marked passage (which pauses its fade) and zooms in.
// pick() returns a fresh chip each attempt, so a re-render between attempts can't leave a stale target.
export async function showCitation(stage, pick) {
  const { page } = stage
  let jumped = false
  for (let attempt = 0; attempt < 2 && !jumped; attempt++) {
    const chip = await pick()
    if (attempt === 0) await stage.hover(chip, 1300)
    await stage.click(chip)
    jumped = await outcome(page).first()
      .waitFor({ state: 'attached', timeout: 8_000 })
      .then(() => true)
      .catch(() => false)
  }
  if (!jumped) throw new Error('the citation did not open its passage')
  await page.waitForTimeout(900)
  const strong = page.locator('[data-citation-highlight="strong"]')
  const region = page.locator('[data-citation-region]')
  const target = (await strong.count()) > 0 ? strong.first() : (await region.count()) > 0 ? region.first() : null
  if (target) {
    await stage.recorder.hover(target, { timeout: 5_000 })
    await stage.zoom(target, 1.6, 2600)
  } else {
    await page.waitForTimeout(2000)
  }
}
