import { expect } from 'playwright/test'

import { paperByDoi } from '../lib/api.mjs'
import { PAPERS, QUERY } from '../lib/config.mjs'
import { card, firstPage, home, reader, readerStatus } from '../lib/ui.mjs'

// Save the SoK: OpenAlex has no stored copy, so we attach the PDF downloaded from arXiv.
export default {
  id: '03-attach',
  async run(s, ctx) {
    const { page } = s
    await s.go('/', home(page))
    // The sidebar's Recent entry reopens the search without adding another history entry.
    await s.click(page.getByRole('link', { name: QUERY, exact: true }))
    const sok = card(page, PAPERS.sok.doi)
    await expect(sok).toBeVisible({ timeout: 45_000 })
    await s.pause(1200)
    await s.smooth(sok)
    await s.hover(sok.getByRole('heading', { level: 2 }), 1000)

    await s.click(sok.getByRole('button', { name: 'Save to library' }))
    const open = sok.getByRole('link', { name: 'Open paper' })
    await expect(open).toBeVisible({ timeout: 20_000 })
    await s.pause(1200)
    await s.click(open)

    const r = reader(page)
    const missing = r.getByText(/OpenAlex doesn.t have this PDF/)
    await s.lapse('openalex lookup', () => expect(missing).toBeVisible({ timeout: 120_000 }), {
      status: readerStatus(page),
    })
    s.mark('missing')
    ctx.sok = (await paperByDoi(PAPERS.sok.doi)).id
    await s.pause(1500)
    await s.hover(r.getByRole('link', { name: 'Open the paper' }), 1400)

    s.prepareFile(PAPERS.sok.file)
    await s.click(r.getByRole('button', { name: 'Upload PDF', exact: true }))
    await s.lapse('arxiv pdf preparation', () => expect(firstPage(page)).toBeVisible({ timeout: 240_000 }), {
      status: readerStatus(page),
    })
    s.mark('pdf')
    await s.pause(2500)
  },
}
