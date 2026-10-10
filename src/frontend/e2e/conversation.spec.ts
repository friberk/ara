import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

// Conversation pane E2E (ARA-036): E2E-04 summary and E2E-05 questions, against the fixture stack
// (compose.e2e.yaml). Fixture answers mention the Orion-12 dataset and cite a real chunk of the PDF.
const pdfPath = process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf'
type Paper = { id: string; document_status: string }

async function savedPaper(request: APIRequestContext): Promise<Paper> {
  const response = await request.post('/api/v1/papers', { data: { provider: 'openalex', external_id: 'W123456789' } })
  expect(response.ok()).toBeTruthy()
  return response.json() as Promise<Paper>
}
async function readyPaper(request: APIRequestContext): Promise<Paper> {
  const paper = await savedPaper(request)
  if (paper.document_status !== 'ready') {
    expect(existsSync(pdfPath), 'Generate the synthetic research.pdf before browser checks').toBeTruthy()
    const upload = await request.post('/api/v1/documents', { multipart: { file: { name: 'research.pdf', mimeType: 'application/pdf', buffer: await readFile(pdfPath) }, paper_id: paper.id, request_id: crypto.randomUUID() } })
    expect(upload.ok()).toBeTruthy()
    await expect.poll(async () => (await (await request.get(`/api/v1/papers/${paper.id}`)).json()).document_status, { timeout: 45_000 }).toBe('ready')
  }
  return paper
}

// Citation chips from the content module (ARA-035), inline and in the Sources group, are named "Source, page N",
// "Source, pages N–M" for a passage that runs onto the next page, then the passage's heading when it has one (ARA-075).
const citationChip = /^Source, pages? \d+/
async function chipPage(chip: Locator) {
  const label = (await chip.getAttribute('aria-label')) ?? (await chip.innerText())
  return Number(label.match(/\d+/)?.[0])
}

// Reader names as shipped on feat/ui-workspace (ARA-037, 79ac582): the PDF scroller is a region named
// "PDF document", each page a group named "Page N", and the jump outcome is announced in a polite status.
const reader = {
  region: (page: Page) => page.getByRole('region', { name: 'PDF document' }),
  page: (page: Page, pageNumber: number) => reader.region(page).getByRole('group', { name: `Page ${pageNumber}`, exact: true }),
  outcome: (page: Page) => page.getByRole('status').filter({ hasText: /cited passage on page|showing page/i }),
}

test('E2E-04 Given ready text, when summarized, then a stored grounded summary appears and survives reload', async ({ page, request }) => {
  const paper = await readyPaper(request)
  await page.goto(`/papers/${paper.id}`)
  const summary = page.getByRole('article', { name: 'Paper summary' })
  const generate = summary.getByRole('button', { name: 'Generate summary', exact: true })
  const toggle = summary.getByRole('button', { name: /^(Show full summary|Collapse summary)$/ })
  // The fixture paper is shared across runs: the first run generates, later runs show the stored summary.
  await expect(generate.or(toggle)).toBeVisible()
  if (await generate.isVisible()) {
    await generate.click()
    // A summary that just finished opens in full, with its page sources.
    await expect(summary.getByRole('button', { name: 'Collapse summary' })).toBeVisible({ timeout: 45_000 })
    await expect(summary.getByRole('button', { name: citationChip }).first()).toBeVisible()
  }
  await expect(summary).toContainText('Orion-12', { timeout: 45_000 })

  await page.reload()
  await expect(summary.getByRole('button', { name: 'Show full summary' })).toBeVisible()
  await expect(summary).toContainText('Orion-12')
  await summary.getByRole('button', { name: 'Show full summary' }).click()
  await expect(summary.getByRole('button', { name: citationChip }).first()).toBeVisible()
})

test('E2E-05 Given a ready paper, when a question and a follow-up are asked, then answers stream with page evidence and persist', async ({ page, request }) => {
  const paper = await readyPaper(request)
  let generations = 0
  page.on('request', (sent) => { if (sent.method() === 'POST' && /\/api\/v1\/chats\/[^/]+\/messages\/stream$/.test(sent.url())) generations++ })
  await page.goto(`/papers/${paper.id}`)

  // The first question comes from a suggestion: it creates the chat, opens its URL and is sent once.
  await page.getByRole('group', { name: 'Suggested questions' }).getByRole('button', { name: 'What datasets are used?', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/papers/${paper.id}/chats/[0-9a-f-]{36}$`))
  const chatUrl = page.url()
  const answers = page.getByRole('article', { name: 'Assistant message' })
  await expect(page.getByRole('button', { name: 'Stop generation' })).toBeVisible()
  await expect(answers.last()).toContainText('Orion-12', { timeout: 45_000 })
  await expect(page.getByRole('button', { name: 'Stop generation' })).toBeHidden()
  expect(generations).toBe(1)

  // A page citation jumps the reader to that page and highlights the cited passage.
  const chip = answers.last().getByRole('button', { name: citationChip }).first()
  const cited = await chipPage(chip)
  expect(cited).toBeGreaterThan(0)
  await chip.click()
  await expect(reader.page(page, cited)).toBeInViewport()
  await expect(reader.outcome(page)).toHaveText(`Highlighted the cited passage on page ${cited}.`)

  // Follow-up in the same chat.
  await page.getByRole('textbox', { name: 'Question about this paper' }).fill('What are the limitations?')
  await page.getByRole('button', { name: 'Ask question', exact: true }).click()
  await expect(answers).toHaveCount(2)
  await expect(answers.last()).toContainText('Orion-12', { timeout: 45_000 })
  await expect(page.getByRole('button', { name: 'Stop generation' })).toBeHidden()
  expect(generations).toBe(2)

  // The first question titled the chat; the switcher and the sidebar's Recent list show it.
  const title = 'What datasets are used'
  await expect(page.getByRole('main').getByRole('button', { name: title, exact: true })).toBeVisible()
  const recent = page.getByRole('link', { name: title, exact: true }).first()
  await expect(recent).toBeVisible()
  await expect(recent).toHaveAttribute('href', /\/chats\//)

  await page.reload()
  expect(page.url()).toBe(chatUrl)
  await expect(page.getByRole('article', { name: 'Your message' })).toHaveCount(2)
  await expect(answers).toHaveCount(2)
  await expect(answers.first()).toContainText('Orion-12')
  expect(generations).toBe(2)
})
