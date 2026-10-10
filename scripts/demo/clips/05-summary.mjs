import { expect } from 'playwright/test'

import { paperByTitle } from '../lib/api.mjs'
import { PAPERS } from '../lib/config.mjs'
import { citationChip, conversation, firstPage, pickChip, settled, showCitation, summaryCard, summaryStage } from '../lib/ui.mjs'

// Summarize the uploaded paper. Its automatic summary finished off camera, so regenerate it to show the run.
export default {
  id: '05-summary',
  async run(s, ctx) {
    const { page } = s
    const paperId = ctx.backrefs ?? (await paperByTitle(PAPERS.backrefs.title)).id
    await s.go(`/papers/${paperId}`, firstPage(page))
    const summary = summaryCard(page)
    const regenerate = summary.getByRole('button', { name: 'Regenerate summary' })
    await expect(regenerate).toBeEnabled({ timeout: 30_000 })
    // The card's text: the old summary stays visible while the new one is written, then is replaced.
    const content = summary.locator('[class*="text-[15.5px]"]')
    const before = (await content.allInnerTexts()).join('\n')
    await s.hover(summary.getByRole('heading', { name: 'Summary', exact: true }).first(), 900)

    await s.click(regenerate)
    await expect(summary.getByRole('progressbar', { name: 'Summary progress' })).toBeVisible({ timeout: 20_000 })
    await s.lapse(
      'summary',
      () => expect(summary.getByRole('button', { name: 'Collapse summary' })).toBeVisible({ timeout: 600_000 }),
      { status: summaryStage(page) },
    )
    // The card opens as soon as the job ends, sometimes still on the old text; wait for the new summary.
    await s.lapse('summary refresh', async () => {
      await expect.poll(async () => (await content.allInnerTexts()).join('\n'), { timeout: 60_000 }).not.toBe(before)
      await settled(content)
    })
    s.mark('summary')
    await s.pause(1200)

    await s.scrollBy(conversation(page), 260)
    await s.pause(1800)
    await showCitation(s, () => pickChip(summary.getByRole('button', { name: citationChip })))
  },
}
