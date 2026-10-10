import { expect } from 'playwright/test'

import { PAPERS } from '../lib/config.mjs'
import { answerComplete, answers, home, showCitation } from '../lib/ui.mjs'

// One question over two papers, mentioned with @; a citation to the second paper opens it in a new reader tab.
export default {
  id: '07-multi',
  async run(s) {
    const { page } = s
    await s.go('/', home(page))
    const topic = page.getByRole('textbox', { name: 'Research topic' })
    await s.click(topic)
    await s.keys('How does @', 70)
    await expect(page.getByPlaceholder('Mention a paper')).toBeFocused({ timeout: 10_000 })
    await s.pause(700)
    await s.click(page.getByRole('option', { name: new RegExp(PAPERS.backrefs.title) }))
    await expect(page.getByRole('textbox', { name: 'Question about this paper' })).toBeFocused()

    await s.keys('go beyond the ReDoS detectors that @', 50)
    await expect(page.getByPlaceholder('Mention a paper')).toBeFocused({ timeout: 10_000 })
    await s.pause(700)
    await s.click(page.getByRole('option', { name: /SoK: A Literature/ }))
    await expect(page.getByRole('textbox', { name: 'Question about these papers' })).toBeFocused()
    await s.keys('surveys?', 60)
    await s.pause(800)

    await s.click(page.getByRole('button', { name: 'Ask question' }))
    await page.waitForURL(/\/papers\/[0-9a-f-]{36}\/chats\/[0-9a-f-]{36}$/, { timeout: 30_000 })
    await expect(page.getByRole('list', { name: 'Papers in this conversation' }).getByRole('listitem')).toHaveCount(2, {
      timeout: 20_000,
    })
    await s.lapse('answer', () => answerComplete(page), { status: answers(page).last() })
    s.mark('answer')
    await s.pause(1500)

    // A chip naming the SoK's first author opens that paper's PDF beside the first one. Picker options and
    // paper chips start with their PDF state ("PDF attached …"), so names are matched unanchored.
    const sources = answers(page).last().getByRole('group', { name: 'Sources' })
    const other = sources.getByRole('button', { name: /^Source, Bhuiyan/ })
    const tabs = page.getByRole('tablist', { name: 'Open PDFs' })
    if ((await other.count()) > 0) {
      await showCitation(s, async () => other.first())
    } else {
      await s.click(page.getByRole('list', { name: 'Papers in this conversation' }).getByRole('button', { name: /SoK: A Literature/ }))
      await s.pause(2500)
    }
    await expect(tabs.getByRole('tab', { selected: true })).toHaveText(/^Bhuiyan/, { timeout: 20_000 })
    await s.pause(1200)
  },
}
