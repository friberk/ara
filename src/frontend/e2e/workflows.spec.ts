import { expect, test, type APIRequestContext } from '@playwright/test'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

const pdfPath = process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf'
const title = 'Traceable Research Systems'
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

test('E2E-01 Given each provider, when a topic is searched, then normalized papers appear', async ({ page }) => {
  await page.goto('/search')
  await page.getByLabel('Research topic').fill('research')
  for (const provider of ['openalex', 'semantic_scholar']) {
    await page.getByLabel('Academic provider').selectOption(provider)
    await page.getByRole('button', { name: 'Search papers', exact: true }).click()
    await expect(page.getByRole('heading', { name: title })).toBeVisible()
    await expect(page.getByText('Ada Researcher', { exact: false }).first()).toBeVisible()
  }
})

test('E2E-02 Given a search result, when saved and refreshed, then it stays in the library', async ({ page }) => {
  await page.goto('/search?q=research&provider=openalex')
  await page.getByRole('button', { name: 'Save to library' }).click()
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Library', exact: true }).click()
  await expect(page.getByRole('link', { name: title, exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('link', { name: title, exact: true })).toBeVisible()
  await page.goto('/search?q=research&provider=semantic_scholar')
  await page.getByRole('button', { name: 'Save to library' }).click()
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Library', exact: true }).click()
  await expect(page.getByRole('link', { name: title, exact: true })).toHaveCount(1)
})

test('E2E-03 Given a PDF, when uploaded, then original and extracted metadata are ready', async ({ page, request }) => {
  const paper = await savedPaper(request)
  await page.goto(`/papers/${paper.id}`)
  await page.getByLabel('PDF file').setInputFiles(pdfPath)
  await page.getByRole('button', { name: 'Upload PDF', exact: true }).click()
  await expect(page.getByText('PDF uploaded. Processing continues in the background.')).toBeVisible()
  await expect(page.getByText('Ready to read', { exact: true }).first()).toBeVisible({ timeout: 45_000 })
  await expect(page.getByRole('link', { name: 'Open original PDF' })).toBeVisible()
  await expect(page.getByText('Ada Researcher', { exact: true }).first()).toBeVisible()
})

test('E2E-04 Given ready text, when summarized, then a stored grounded summary appears', async ({ page, request }) => {
  const paper = await readyPaper(request)
  await page.goto(`/papers/${paper.id}`)
  await page.getByRole('button', { name: 'Generate summary', exact: true }).click()
  await expect(page.locator('.summary-item').first()).toContainText('Orion-12', { timeout: 45_000 })
  await expect(page.locator('.summary-item').first().getByRole('button', { name: /Page/ }).first()).toBeVisible()
  await page.reload()
  await expect(page.locator('.summary-item').first()).toContainText('Orion-12')
})

test('E2E-05 Given a ready paper, when asked a question, then stream, sources and history persist', async ({ page, request }) => {
  const paper = await readyPaper(request)
  await page.goto(`/papers/${paper.id}`)
  await page.getByRole('tab', { name: 'Questions' }).click()
  await page.getByRole('button', { name: 'New conversation', exact: true }).click()
  await page.getByLabel('Question about this paper').fill('Which dataset is used?')
  await page.getByRole('button', { name: 'Ask question', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Stop generation' })).toBeVisible()
  await expect(page.locator('.message-assistant').last()).toContainText('Orion-12')
  await expect(page.getByRole('button', { name: 'Stop generation' })).not.toBeVisible()
  await page.locator('.message-assistant').last().getByRole('button', { name: /Page/ }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('Source')
  await page.keyboard.press('Escape')
  await page.getByLabel('Question about this paper').fill('What are the limitations?')
  await page.getByRole('button', { name: 'Ask question', exact: true }).click()
  await expect(page.locator('.message-assistant')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Stop generation' })).not.toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'Questions' }).click()
  await page.locator('.conversation-link').first().click()
  await expect(page.locator('.message-assistant')).toHaveCount(2)
})

test('Mobile workspace and keyboard controls remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/search')
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
})
