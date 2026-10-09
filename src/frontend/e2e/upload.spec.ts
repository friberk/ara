import { expect, test } from '@playwright/test'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

// Upload journeys (ARA-086) against the isolated e2e stack and its synthetic research.pdf. Each run appends a unique
// comment so the bytes are new; identical bytes are deduplicated into the existing paper.
const pdfPath = process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf'
async function freshCopy(label: string) {
  expect(existsSync(pdfPath), 'Generate the synthetic research.pdf before browser checks').toBeTruthy()
  return Buffer.concat([await readFile(pdfPath), Buffer.from(`\n% ${label} ${crypto.randomUUID()}\n`)])
}

test('Given a PDF chosen on home, Then it uploads at once and its paper opens through one step list to the reader', async ({ page }) => {
  await page.goto('/')
  const picker = page.waitForEvent('filechooser')
  await page.getByRole('list', { name: 'Suggestions' }).getByRole('button', { name: 'Upload a PDF' }).click()
  await (await picker).setFiles({ name: 'home-upload.pdf', mimeType: 'application/pdf', buffer: await freshCopy('home') })
  await page.waitForURL(/\/papers\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/in the background/i)).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Page 1' }).locator('canvas')).toBeVisible({ timeout: 45_000 })
  await expect(page.getByText('Ready to read', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { level: 1, name: 'Traceable Research Systems' })).toBeVisible()
})

test('Given two new PDFs and a repeat picked in the library, Then each gets its own row and the repeat opens its paper', async ({ page }) => {
  const first = await freshCopy('library-a')
  await page.goto('/library')
  await page.getByLabel('PDF files').setInputFiles([
    { name: 'library-a.pdf', mimeType: 'application/pdf', buffer: first },
    { name: 'library-b.pdf', mimeType: 'application/pdf', buffer: await freshCopy('library-b') },
  ])
  const uploads = page.getByRole('list', { name: 'Uploads' })
  await expect(uploads.getByRole('listitem')).toHaveCount(2)
  await expect(uploads.getByRole('link', { name: 'Open library-a.pdf' })).toBeVisible()
  await expect(uploads.getByRole('link', { name: 'Open library-b.pdf' })).toBeVisible()
  await page.getByLabel('PDF files').setInputFiles({ name: 'library-a-again.pdf', mimeType: 'application/pdf', buffer: first })
  const repeat = uploads.getByRole('listitem').filter({ hasText: 'library-a-again.pdf' })
  await expect(repeat.getByText('Already in your library')).toBeVisible()
  const original = await uploads.getByRole('link', { name: 'Open library-a.pdf' }).getAttribute('href')
  await expect(repeat.getByRole('link', { name: 'Open library-a-again.pdf' })).toHaveAttribute('href', original ?? '')
  await expect(uploads.getByText('Ready', { exact: true })).toHaveCount(2, { timeout: 60_000 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('Given Settings, When Semantic Scholar is chosen as the metadata source, Then it stays chosen after a reload', async ({ page }) => {
  await page.goto('/settings')
  const section = page.getByRole('region', { name: 'Metadata source' })
  await section.getByRole('radio', { name: 'Semantic Scholar' }).click()
  await expect(section.getByText('Metadata source saved.')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('region', { name: 'Metadata source' }).getByRole('radio', { name: 'Semantic Scholar' })).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('region', { name: 'Metadata source' }).getByRole('radio', { name: 'OpenAlex' }).click()
  await expect(page.getByRole('region', { name: 'Metadata source' }).getByText('Metadata source saved.')).toBeVisible()
})
