import { expect } from 'playwright/test'

import { get, paperByTitle } from '../lib/api.mjs'
import { PAPERS } from '../lib/config.mjs'
import { firstPage, home, reader, readerStatus } from '../lib/ui.mjs'

// Upload the USENIX '26 PDF from Home; its details are read from the PDF, then matched to OpenAlex.
export default {
  id: '04-upload',
  async run(s, ctx) {
    const { page } = s
    await s.go('/', home(page))
    await s.hover(home(page), 600)

    s.prepareFile(PAPERS.backrefs.file)
    await s.click(page.getByRole('list', { name: 'Suggestions' }).getByRole('button', { name: 'Upload a PDF' }))
    await page.waitForURL(/\/papers\/[0-9a-f-]{36}$/, { timeout: 30_000 })
    const paperId = page.url().split('/').at(-1)
    ctx.backrefs = paperId

    await s.lapse('pdf preparation', () => expect(firstPage(page)).toBeVisible({ timeout: 240_000 }), {
      status: readerStatus(page),
    })
    s.mark('pdf')
    // The catalog lookup that completes the details runs right after the PDF is ready.
    await s.lapse('details lookup', async () => {
      await expect
        .poll(async () => (await get(`/jobs?paper_id=${paperId}&kind=metadata&active=true`)).items.length, {
          timeout: 120_000,
          intervals: [1000],
        })
        .toBe(0)
    })
    await expect(page.getByRole('heading', { level: 1, name: new RegExp(PAPERS.backrefs.title) })).toBeVisible({
      timeout: 30_000,
    })
    await s.pause(1200)

    const r = reader(page)
    const more = r.getByRole('button', { name: 'Show more' })
    if (await more.isVisible()) {
      await s.click(more)
      await s.pause(2600)
    }
    await s.click(page.getByRole('button', { name: 'Sources and search index' }))
    const dialog = page.getByRole('dialog', { name: 'Sources and search index' })
    await expect(dialog.getByText('Where this information came from')).toBeVisible({ timeout: 10_000 })
    await s.pause(3500)
    await s.escape(page.getByRole('dialog'))
    await s.pause(800)
    ctx.backrefs = (await paperByTitle(PAPERS.backrefs.title)).id
  },
}
