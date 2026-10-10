import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// Deleting papers and editing their details from the Library (ARA-095), against the isolated e2e stack.
// Each journey uploads its own small text PDF with a unique title, so it never touches the fixture paper that the
// other journeys share.

/** A one-page text PDF whose first line is `title`, with correct cross-reference offsets. */
function textPdf(title: string): Buffer {
  const content = `BT /F1 20 Tf 72 700 Td (${title}) Tj ET\nBT /F1 11 Tf 72 660 Td (A disposable paper for the library journeys.) Tj ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let body = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(body)); body += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const xref = Buffer.byteLength(body)
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}`
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(body, 'latin1')
}

type Paper = { id: string; title: string | null; document_status: string }

/** Uploads a disposable paper and waits until its PDF is read. */
async function disposablePaper(request: APIRequestContext, label: string): Promise<Paper> {
  const title = `Disposable ${label} ${crypto.randomUUID().slice(0, 8)}`
  const upload = await request.post('/api/v1/documents', { multipart: { file: { name: `${label}.pdf`, mimeType: 'application/pdf', buffer: textPdf(title) }, request_id: crypto.randomUUID() } })
  expect(upload.ok()).toBeTruthy()
  const { paper_id: id } = await upload.json() as { paper_id: string }
  await expect.poll(async () => ((await (await request.get(`/api/v1/papers/${id}`)).json()) as Paper).document_status, { timeout: 45_000 }).toBe('ready')
  return (await request.get(`/api/v1/papers/${id}`)).json() as Promise<Paper>
}

async function openRowActions(page: Page, name: string) {
  await page.getByRole('main').getByRole('button', { name: `Actions for “${name}”` }).click()
}

test('Given a library row, When its details are edited and it is deleted, Then the dialog says what goes and the paper is gone', async ({ page, request }) => {
  const paper = await disposablePaper(request, 'edit-delete')
  const renamed = `${paper.title} renamed`
  await page.goto(`/library?q=${encodeURIComponent(paper.title ?? '')}`)
  await openRowActions(page, paper.title ?? '')
  await page.getByRole('menuitem', { name: 'Edit details' }).click()
  const editor = page.getByRole('dialog', { name: 'Edit details' })
  await editor.getByRole('textbox', { name: 'Title' }).fill(renamed)
  await editor.getByRole('textbox', { name: 'Venue' }).fill('E2E Workshop')
  await editor.getByRole('button', { name: 'Save details' }).click()
  await expect(editor).toHaveCount(0)
  const saved = await (await request.get(`/api/v1/papers/${paper.id}`)).json() as { title: string; venue: string; metadata_provenance: Record<string, { source: string }> }
  expect([saved.title, saved.venue, saved.metadata_provenance.venue?.source]).toEqual([renamed, 'E2E Workshop', 'manual'])

  await page.goto(`/library?q=${encodeURIComponent(renamed)}`)
  await openRowActions(page, renamed)
  await page.getByRole('menuitem', { name: 'Delete…' }).click()
  const dialog = page.getByRole('alertdialog', { name: `Delete “${renamed}”?` })
  const removed = dialog.getByRole('list', { name: 'What will be deleted' })
  await expect(removed.getByRole('listitem').first()).toHaveText('The paper and its details')
  await expect(removed).toContainText('1 PDF, with its text and search index')
  await dialog.getByRole('button', { name: 'Delete paper' }).click()
  await expect(page.getByText(`Deleted “${renamed}”`)).toBeVisible()
  await expect(page.getByRole('main').getByRole('link', { name: renamed })).toHaveCount(0)
  expect((await request.get(`/api/v1/papers/${paper.id}`)).status()).toBe(404)

  // An old link to the deleted paper lands in the Library with a short note.
  await page.goto(`/papers/${paper.id}`)
  await expect(page).toHaveURL(/\/library$/)
  await expect(page.getByText('That paper isn’t in your library anymore. It may have been deleted.')).toBeVisible()
})

test('Given several selected papers, When they are deleted together, Then one confirmation names the count and both go', async ({ page, request }) => {
  const first = await disposablePaper(request, 'bulk-a')
  const second = await disposablePaper(request, 'bulk-b')
  await page.goto('/library?q=Disposable%20bulk')
  const main = page.getByRole('main')
  for (const paper of [first, second]) await main.getByRole('checkbox', { name: `Select “${paper.title}”` }).check()
  const toolbar = page.getByRole('toolbar', { name: 'Selected papers' })
  await expect(toolbar).toContainText('2 selected')
  await toolbar.getByRole('button', { name: 'Delete…' }).click()
  const dialog = page.getByRole('alertdialog', { name: 'Delete 2 papers?' })
  await expect(dialog.getByRole('list', { name: 'What will be deleted' })).toContainText('2 PDFs, with their text and search index')
  await dialog.getByRole('button', { name: 'Delete 2 papers' }).click()
  await expect(page.getByText('Deleted 2 papers')).toBeVisible()
  for (const paper of [first, second]) expect((await request.get(`/api/v1/papers/${paper.id}`)).status()).toBe(404)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
