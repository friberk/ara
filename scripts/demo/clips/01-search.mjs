import { expect } from 'playwright/test'

import { PAPERS, QUERY } from '../lib/config.mjs'
import { card, home } from '../lib/ui.mjs'

// Search OpenAlex from an empty app and read one result: title, authors, year, abstract and links.
export default {
  id: '01-search',
  async run(s) {
    const { page } = s
    await s.go('/', home(page))
    await expect(page.getByText('Searches and conversations appear here.')).toBeVisible()
    await s.hover(home(page), 700)

    await s.click(page.getByRole('button', { name: /^Academic provider:/ }))
    await expect(page.getByRole('menuitemradio', { name: /^OpenAlex/ })).toBeVisible()
    await s.pause(1400)
    await s.escape(page.getByRole('menu'))

    await s.type(page.getByRole('textbox', { name: 'Research topic' }), QUERY, 55)
    await s.pause(400)
    await s.click(page.getByRole('button', { name: 'Search papers', exact: true }))
    const results = page.getByRole('list', { name: 'Search results' })
    await s.lapse('search', () => expect(results).toBeVisible({ timeout: 45_000 }))
    s.mark('results')
    await s.pause(1800)

    const fse = card(page, PAPERS.fse.doi)
    await s.smooth(fse)
    await s.hover(fse.getByRole('heading', { level: 2 }), 900)
    const more = fse.getByRole('button', { name: 'Show more' })
    if (await more.isVisible()) {
      await s.click(more)
      await s.pause(2200)
    }
    // The links shown depend on the record: DOI, a catalog page when it differs from the DOI, and the PDF.
    for (const name of [/^DOI/, /^OpenAlex/, /^PDF/]) {
      const link = fse.getByRole('link', { name })
      if (await link.isVisible()) await s.hover(link, 900)
    }
  },
}
