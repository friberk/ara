import { expect, test, type APIRequestContext } from '@playwright/test'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

// Chats over several papers (ARA-088) against the fixture stack (compose.e2e.yaml). The second paper is a separate
// synthetic PDF with its own embedded title, so its upload becomes its own library paper:
//   uv run --with pymupdf==1.26.7 python tests/fixtures/create_pdf.py --second /tmp/ara-fixtures/second.pdf
// The fixture model cites the first passage of each paper's evidence group.
const pdfPath = process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf'
const secondPath = process.env.E2E_SECOND_PDF_PATH ?? '/tmp/ara-fixtures/second.pdf'
const firstTitle = 'Traceable Research Systems'
const secondTitle = 'Sparse Indexes for Lab Notebooks'
type Paper = { id: string; document_status: string }

async function ready(request: APIRequestContext, paperId: string) {
  await expect.poll(async () => (await (await request.get(`/api/v1/papers/${paperId}`)).json()).document_status, { timeout: 45_000 }).toBe('ready')
}

async function fixturePaper(request: APIRequestContext): Promise<Paper> {
  const response = await request.post('/api/v1/papers', { data: { provider: 'openalex', external_id: 'W123456789' } })
  expect(response.ok()).toBeTruthy()
  const paper = await response.json() as Paper
  if (paper.document_status !== 'ready') {
    expect(existsSync(pdfPath), 'Generate the synthetic research.pdf before browser checks').toBeTruthy()
    const upload = await request.post('/api/v1/documents', { multipart: { file: { name: 'research.pdf', mimeType: 'application/pdf', buffer: await readFile(pdfPath) }, paper_id: paper.id, request_id: crypto.randomUUID() } })
    expect(upload.ok()).toBeTruthy()
    await ready(request, paper.id)
  }
  return paper
}

/** The second paper, uploaded once; a repeat upload answers with the same paper. */
async function secondPaper(request: APIRequestContext): Promise<Paper> {
  expect(existsSync(secondPath), 'Generate the second synthetic PDF (create_pdf.py --second) before browser checks').toBeTruthy()
  const upload = await request.post('/api/v1/documents', { multipart: { file: { name: 'second.pdf', mimeType: 'application/pdf', buffer: await readFile(secondPath) }, request_id: crypto.randomUUID() } })
  expect(upload.ok()).toBeTruthy()
  const { paper_id: paperId } = await upload.json() as { paper_id: string }
  await ready(request, paperId)
  return { id: paperId, document_status: 'ready' }
}

test('ARA-088 Given two ready papers, when one chat compares them, then each is cited by name, opens in its own reader tab and lists the chat', async ({ page, request }) => {
  const first = await fixturePaper(request)
  const second = await secondPaper(request)

  await page.goto('/')
  await page.getByRole('button', { name: 'Ask about a library paper' }).click()
  await page.getByRole('option', { name: new RegExp(firstTitle) }).click()
  // Typing @ opens the same picker for the second paper.
  await page.getByRole('textbox', { name: 'Question about this paper' }).press('@')
  await page.getByRole('option', { name: new RegExp(secondTitle) }).click()
  const question = page.getByRole('textbox', { name: 'Question about these papers' })
  await question.fill('How do the two papers compare on accuracy?')
  await page.getByRole('button', { name: 'Ask question' }).click()

  await expect(page).toHaveURL(new RegExp(`/papers/${first.id}/chats/[0-9a-f-]{36}$`))
  const chatUrl = page.url()
  const chips = page.getByRole('list', { name: 'Papers in this conversation' })
  await expect(chips.getByRole('listitem')).toHaveCount(2)

  const answer = page.getByRole('article', { name: 'Assistant message' }).last()
  const sources = answer.getByRole('group', { name: 'Sources' })
  await expect(sources.getByRole('button', { name: /^Source, Researcher 2024, pages? \d+/ })).toBeVisible({ timeout: 45_000 })
  const secondChip = sources.getByRole('button', { name: /^Source, Analyst( \d{4})?, pages? \d+/ })
  await expect(secondChip).toBeVisible()

  // The other paper's citation opens its PDF in a new reader tab; the first paper's tab stays open.
  await secondChip.click()
  const tabs = page.getByRole('tablist', { name: 'Open PDFs' })
  await expect(tabs.getByRole('tab', { selected: true })).toHaveText(/^Analyst/)
  await expect(tabs.getByRole('tab')).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'PDF document' }).last()).toBeVisible()

  // The chat is listed under the second paper too, and opens at its first paper's address.
  await page.goto(`/papers/${second.id}`)
  await page.getByRole('button', { name: 'New conversation' }).first().click()
  await page.getByRole('menuitemradio', { name: /How do the two papers compare/ }).click()
  await expect(page).toHaveURL(chatUrl)

  // Removing the second paper keeps the answer's citation to it.
  await chips.getByRole('button', { name: `Remove ${secondTitle} from this conversation` }).click()
  await expect(chips.getByRole('listitem')).toHaveCount(1)
  await expect(page.getByRole('article', { name: 'Assistant message' }).last().getByRole('group', { name: 'Sources' }).getByRole('button', { name: /^Source, Analyst/ })).toBeVisible()
})
