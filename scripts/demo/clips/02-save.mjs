import { expect } from 'playwright/test'

import { paperByDoi } from '../lib/api.mjs'
import { PAPERS, QUERY } from '../lib/config.mjs'
import { card, firstPage, readerStatus, summaryCard } from '../lib/ui.mjs'

// Save the FSE '18 paper; OpenAlex has a stored copy, so its PDF arrives without a click.
export default {
  id: '02-save',
  async run(s, ctx) {
    const { page } = s
    const fse = card(page, PAPERS.fse.doi)
    // A deep-linked search is not added to the search history.
    await s.go(`/search?q=${encodeURIComponent(QUERY)}&provider=openalex`, fse)
    await s.smooth(fse)
    await s.pause(600)

    await s.click(fse.getByRole('button', { name: 'Save to library' }))
    const open = fse.getByRole('link', { name: 'Open paper' })
    await expect(open).toBeVisible({ timeout: 20_000 })
    await s.pause(1600)
    await s.click(open)

    await s.lapse('pdf retrieval', () => expect(firstPage(page)).toBeVisible({ timeout: 240_000 }), {
      status: readerStatus(page),
    })
    s.mark('pdf')
    ctx.fse = (await paperByDoi(PAPERS.fse.doi)).id
    await s.pause(1500)

    const progress = summaryCard(page).getByRole('progressbar', { name: 'Summary progress' })
    await s.lapse('summary start', () => expect(progress).toBeVisible({ timeout: 90_000 }))
    await s.hover(summaryCard(page).getByRole('heading', { name: 'Summary', exact: true }).first(), 2200)
  },
}
