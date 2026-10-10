import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

// Upload journeys (ARA-086) against the isolated e2e stack and its synthetic research.pdf. Each run appends a unique
// comment so the bytes are new. The research journey saves the same work ("Traceable Research Systems"), so these
// uploads are library matches: they join that paper, or ask to replace its PDF, and never duplicate it.
const pdfPath = process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf'
const title = 'Traceable Research Systems'
async function freshCopy(label: string) {
  expect(existsSync(pdfPath), 'Generate the synthetic research.pdf before browser checks').toBeTruthy()
  return Buffer.concat([await readFile(pdfPath), Buffer.from(`\n% ${label} ${crypto.randomUUID()}\n`)])
}
async function copiesInLibrary(request: APIRequestContext) {
  const page = await (await request.get('/api/v1/papers?limit=100')).json() as { items: { title: string | null }[] }
  return page.items.filter((paper) => paper.title?.toLowerCase() === title.toLowerCase()).length
}
async function savedFixture(request: APIRequestContext) {
  expect((await request.post('/api/v1/papers', { data: { provider: 'openalex', external_id: 'W123456789' } })).ok()).toBeTruthy()
}
/** The upload either joined the library paper by itself or asks first; Replace answers the question. */
async function settleMatch(page: Page) {
  const replace = page.getByRole('button', { name: /^(Replace|Attach) PDF$/ })
  await expect(replace.or(page.getByRole('heading', { level: 1, name: title }))).toBeVisible({ timeout: 45_000 })
  if (await replace.isVisible()) await replace.click()
}

test('Given a PDF of a library paper chosen on home, Then it uploads at once and opens that paper without a duplicate', async ({ page, request }) => {
  await savedFixture(request)
  await page.goto('/')
  const picker = page.waitForEvent('filechooser')
  await page.getByRole('list', { name: 'Suggestions' }).getByRole('button', { name: 'Upload a PDF' }).click()
  await (await picker).setFiles({ name: 'home-upload.pdf', mimeType: 'application/pdf', buffer: await freshCopy('home') })
  await page.waitForURL(/\/papers\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/in the background/i)).toHaveCount(0)
  await settleMatch(page)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Page 1' }).locator('canvas')).toBeVisible({ timeout: 45_000 })
  expect(await copiesInLibrary(request)).toBe(1)
})

test('Given two new copies picked in the library, Then each row carries its own outcome and Cancel discards one', async ({ page, request }) => {
  await savedFixture(request)
  await page.goto('/library')
  await page.getByLabel('PDF files').setInputFiles([
    { name: 'library-a.pdf', mimeType: 'application/pdf', buffer: await freshCopy('library-a') },
    { name: 'library-b.pdf', mimeType: 'application/pdf', buffer: await freshCopy('library-b') },
  ])
  const uploads = page.getByRole('list', { name: 'Uploads' })
  await expect(uploads.getByRole('listitem')).toHaveCount(2)
  // The paper already has a PDF from earlier journeys, so both rows ask; cancel each and nothing is added.
  for (const name of ['library-a.pdf', 'library-b.pdf']) {
    const row = uploads.getByRole('listitem').filter({ hasText: name })
    const cancel = row.getByRole('button', { name: 'Cancel' })
    await expect(cancel.or(row.getByText(/^Added to/))).toBeVisible({ timeout: 45_000 })
    if (await cancel.isVisible()) {
      await cancel.click()
      await expect(row).toHaveCount(0)
    }
  }
  expect(await copiesInLibrary(request)).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('Given Settings, When Semantic Scholar is chosen for paper details, Then it stays chosen after a reload', async ({ page }) => {
  await page.goto('/?settings=library')
  const section = page.getByRole('region', { name: 'Paper details' })
  await section.getByRole('radio', { name: 'Semantic Scholar' }).check()
  await expect(section.getByText('Saved', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('region', { name: 'Paper details' }).getByRole('radio', { name: 'Semantic Scholar' })).toBeChecked()
  await page.getByRole('region', { name: 'Paper details' }).getByRole('radio', { name: 'OpenAlex' }).check()
  await expect(page.getByRole('region', { name: 'Paper details' }).getByText('Saved', { exact: true })).toBeVisible()
})
