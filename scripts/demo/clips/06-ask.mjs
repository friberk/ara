import { expect } from 'playwright/test'

import { paperByDoi } from '../lib/api.mjs'
import { PAPERS } from '../lib/config.mjs'
import { answerComplete, answers, citationChip, firstPage, pickChip, showCitation } from '../lib/ui.mjs'

// Ask the SoK one of hw1's example questions; the answer cites pages that open in the reader.
export default {
  id: '06-ask',
  async run(s, ctx) {
    const { page } = s
    const paperId = ctx.sok ?? (await paperByDoi(PAPERS.sok.doi)).id
    const suggested = page.getByRole('group', { name: 'Suggested questions' })
    await s.go(`/papers/${paperId}`, firstPage(page))
    await expect(suggested).toBeVisible({ timeout: 30_000 })

    await s.click(page.getByRole('button', { name: /^Model: / }))
    const effort = page.getByRole('menuitem', { name: /^Reasoning effort/ })
    await expect(effort).toBeVisible()
    await s.pause(900)
    await s.hover(effort, 1800)
    await s.escape(page.getByRole('menu'))
    await s.pause(500)

    await s.click(suggested.getByRole('button', { name: 'What are the major limitations?', exact: true }))
    await page.waitForURL(/\/chats\/[0-9a-f-]{36}$/, { timeout: 30_000 })
    // Streaming text keeps changing, so it plays at normal speed; only the quiet search before it is compressed.
    await s.lapse('answer', () => answerComplete(page), { status: answers(page).last() })
    s.mark('answer')
    await s.pause(1500)

    const answer = answers(page).last()
    await showCitation(s, () => pickChip(answer.getByRole('button', { name: citationChip })))

    await s.hover(page.getByRole('button', { name: /^Context \d+% used/ }), 2800)
    await s.hover(page.getByRole('heading', { level: 1 }), 600)
  },
}
