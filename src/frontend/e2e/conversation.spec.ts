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

// Citation chips are rendered by the content module (ARA-035) as "Page N" or "p. N".
const citationChip = /(page|p\.)\s*\d+/i
async function chipPage(chip: Locator) {
  const label = (await chip.getAttribute('aria-label')) ?? (await chip.innerText())
  return Number(label.match(/\d+/)?.[0])
}

// Reader contract (ARA-037). The workspace reader is built in parallel; these are the accessible names this
// spec relies on, kept in one place so they can be aligned with the shipped reader.
const reader = {
  region: (page: Page) => page.getByRole('region', { name: 'PDF reader' }),
  /** The reader states the outcome of a citation jump (WorkspaceContext.reportHighlight) in a polite status. */
  outcome: (page: Page, pageNumber: number) => page.getByRole('status').filter({ hasText: new RegExp(`page ${pageNumber}\\b`, 'i') }),
}

test('E2E-04 Given ready text, when summarized, then a stored grounded summary appears and survives reload', async ({ page, request }) => {
  const paper = await readyPaper(request)
  await page.goto(`/papers/${paper.id}`)
  const summary = page.getByRole('article', { name: 'Paper summary' })
  const generate = summary.getByRole('button', { name: 'Generate summary', exact: true })
  const versions = summary.getByRole('button', { name: /^Version \d+ of \d+$/ })
  // The fixture paper is shared across runs: the first run has no summary, later runs add a version.
  await expect(generate.or(versions)).toBeVisible()
  const before = (await versions.isVisible()) ? Number((await versions.innerText()).match(/of (\d+)/)?.[1]) : 0
  if (before) {
    await versions.click()
    await page.getByRole('menuitem', { name: 'Generate summary' }).click()
  } else {
    await generate.click()
  }
  const latest = `Version ${before + 1} of ${before + 1}`
  await expect(summary.getByRole('button', { name: latest })).toBeVisible({ timeout: 45_000 })
  await expect(summary).toContainText('Orion-12')
  // A summary that just finished opens in full, with its page sources.
  await expect(summary.getByRole('button', { name: 'Collapse summary' })).toBeVisible()
  await expect(summary.getByRole('button', { name: citationChip }).first()).toBeVisible()

  await page.reload()
  await expect(summary.getByRole('button', { name: latest })).toBeVisible()
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
  await expect(reader.region(page)).toBeVisible()
  await expect(reader.outcome(page, cited)).toContainText(/highlighted/i)
  await expect(reader.outcome(page, cited)).not.toContainText(/could not/i)

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
