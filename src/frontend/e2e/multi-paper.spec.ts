import { expect, test } from '@playwright/test'
import { firstTitle, fixturePaper, secondPaper, secondTitle } from './library-papers'

// Chats over several papers (ARA-088) against the fixture stack (compose.e2e.yaml); see library-papers.ts for the PDFs.
// The fixture model cites the first passage of each paper's evidence group.
test('ARA-088 Given two ready papers, when one chat compares them, then each is cited by name, opens in its own reader tab and lists the chat', async ({ page, request }) => {
  const first = await fixturePaper(request)
  const second = await secondPaper(request)

  await page.goto('/')
  await page.getByRole('button', { name: 'Ask about a library paper' }).click()
  await page.getByRole('option', { name: new RegExp(firstTitle) }).click()
  // Typing @ opens the same picker for the second paper, which becomes a pill (ARA-096). Typing goes on after it;
  // fill() would replace the pill and with it the paper.
  await page.getByRole('textbox', { name: 'Question about this paper' }).press('@')
  await page.getByRole('option', { name: new RegExp(secondTitle) }).click()
  const question = page.getByRole('textbox', { name: 'Question about these papers' })
  await expect(question.getByRole('group', { name: new RegExp(secondTitle) })).toBeVisible()
  await page.keyboard.type('How do the two papers compare on accuracy?')
  await page.getByRole('button', { name: 'Ask question' }).click()

  await expect(page).toHaveURL(new RegExp(`/papers/${first.id}/chats/[0-9a-f-]{36}$`))
  const chatUrl = page.url()
  const chips = page.getByRole('list', { name: 'Papers in this conversation' })
  await expect(chips.getByRole('listitem')).toHaveCount(2)

  const answer = page.getByRole('article', { name: 'Assistant message' }).last()
  const sources = answer.getByRole('group', { name: 'Sources' })
  await expect(sources.getByRole('button', { name: /^Source, Researcher.*, pages? \d+/ })).toBeVisible({ timeout: 45_000 })
  const secondChip = sources.getByRole('button', { name: /^Source, Analyst.*, pages? \d+/ })
  await expect(secondChip).toBeVisible()

  // The other paper's citation opens its PDF in a new reader tab; the first paper's tab stays open.
  await secondChip.click()
  const tabs = page.getByRole('tablist', { name: 'Open PDFs' })
  await expect(tabs.getByRole('tab', { selected: true })).toHaveText(/^Analyst/)
  await expect(tabs.getByRole('tab')).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'PDF document' }).last()).toBeVisible()

  // The chat is listed under the second paper too, and opens at its first paper's address.
  await page.goto(`/papers/${second.id}`)
  await page.getByRole('button', { name: 'Chat history' }).click()
  await page.getByRole('option', { name: /How do the two papers compare/ }).click()
  await expect(page).toHaveURL(chatUrl)

  // Removing the second paper keeps the answer's citation to it.
  await chips.getByRole('button', { name: secondTitle }).hover()
  await chips.getByRole('button', { name: `Remove ${secondTitle}` }).click()
  // One paper left: the row goes away.
  await expect(chips).toHaveCount(0)
  await expect(page.getByRole('article', { name: 'Assistant message' }).last().getByRole('group', { name: 'Sources' }).getByRole('button', { name: /^Source, Analyst/ })).toBeVisible()
})
