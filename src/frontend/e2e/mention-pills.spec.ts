import { expect, test } from '@playwright/test'
import { firstTitle, fixturePaper, secondPaper, secondTitle } from './library-papers'

// Paper mention pills (ARA-096) against the fixture stack (compose.e2e.yaml); see library-papers.ts for the PDFs.
// Keys go to the focused editor with page.keyboard, since fill() replaces the editor's whole content, pills included.

test('ARA-096 Given the home composer, when a paper is mentioned with @ and its only pill is deleted, then the paper is no longer chosen', async ({ page, request }) => {
  await fixturePaper(request)
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Research topic' }).click()
  await page.keyboard.type('Compare @')
  await page.getByRole('option', { name: new RegExp(firstTitle) }).click()
  const question = page.getByRole('textbox', { name: 'Question about this paper' })
  const pill = question.getByRole('group', { name: firstTitle })
  await expect(pill).toBeVisible()
  await expect(question).toBeFocused()
  // No chip row: the pill is the attachment. Hovering shows the citation card and the remove button.
  await expect(page.getByRole('button', { name: 'Stop asking about this paper' })).toHaveCount(0)
  await pill.hover()
  await expect(pill.getByRole('button', { name: `Remove ${firstTitle}` })).toBeVisible()
  // The arrow keys step over the space and then select the whole pill; Delete removes it as one unit.
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('Delete')
  await expect(question.getByRole('group')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Research topic' })).toBeVisible()
})

test('ARA-096 Given the home composer, when the @ button picks a paper, then a pill goes in the question and its remove button takes it out', async ({ page, request }) => {
  await fixturePaper(request)
  await page.goto('/')
  await page.getByRole('button', { name: 'Ask about a library paper' }).click()
  await page.getByRole('option', { name: new RegExp(firstTitle) }).click()
  const question = page.getByRole('textbox', { name: 'Question about this paper' })
  const pill = question.getByRole('group', { name: firstTitle })
  await expect(pill).toBeVisible()
  await pill.hover()
  await pill.getByRole('button', { name: `Remove ${firstTitle}` }).click()
  await expect(question.getByRole('group')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Research topic' })).toBeVisible()
})

test('ARA-096 Given a chat over one paper, when a question mentions another, then it is a pill until sent, joins the chat with the question and stays a pill in history', async ({ page, request }) => {
  const first = await fixturePaper(request)
  await secondPaper(request)
  const created = await request.post('/api/v1/chats', { data: { paper_ids: [first.id] } })
  expect(created.ok()).toBeTruthy()
  const chat = await created.json() as { id: string }
  await page.goto(`/papers/${first.id}/chats/${chat.id}`)
  const question = page.getByRole('textbox', { name: 'Question about this paper' })
  const chips = page.getByRole('list', { name: 'Papers in this conversation' })
  await question.click()
  await page.keyboard.type('How does @')
  await page.getByRole('option', { name: new RegExp(secondTitle) }).click()
  await expect(question.getByRole('group', { name: new RegExp(secondTitle) })).toBeVisible()
  // While drafting the paper is only a pill; deleting it changes nothing.
  await expect(chips).toHaveCount(0)
  // The first Backspace takes the space typed after the pill, the second the whole pill.
  await page.keyboard.press('Backspace')
  await page.keyboard.press('Backspace')
  await expect(question.getByRole('group')).toHaveCount(0)
  await expect(chips).toHaveCount(0)

  await page.keyboard.type('@')
  await page.getByRole('option', { name: new RegExp(secondTitle) }).click()
  await expect(question.getByRole('group', { name: new RegExp(secondTitle) })).toBeVisible()
  await page.keyboard.type('compare on accuracy?')
  await page.keyboard.press('Enter')
  await expect(chips.getByRole('listitem')).toHaveCount(2)
  await expect(page.getByRole('article', { name: 'Your message' }).last().getByRole('img', { name: new RegExp(secondTitle) })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Assistant message' }).last().getByRole('group', { name: 'Sources' })).toBeVisible({ timeout: 45_000 })

  await page.reload()
  await expect(page.getByRole('article', { name: 'Your message' }).last().getByRole('img', { name: new RegExp(secondTitle) })).toBeVisible()
})
