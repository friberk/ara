import { expect } from 'playwright/test'

import { PAPERS } from '../lib/config.mjs'

// The library after restarting the app: filter, reload, edit a paper's details, then reopen a chat with ⌘K.
export default {
  id: '08-library',
  restart: true,
  async run(s) {
    const { page } = s
    const main = page.getByRole('main')
    const rows = main.getByRole('list', { name: 'Papers' }).getByRole('listitem')
    await s.go('/library', main.getByRole('heading', { level: 1, name: 'Library' }))
    await expect(rows).toHaveCount(3, { timeout: 30_000 })
    await s.hover(main.getByRole('heading', { level: 1, name: 'Library' }), 1500)

    const filter = main.getByRole('searchbox', { name: 'Filter library' })
    await s.type(filter, 'ReDoS', 90)
    await expect(rows).toHaveCount(2, { timeout: 10_000 })
    await s.pause(1600)
    await page.keyboard.press('ControlOrMeta+a')
    await page.keyboard.press('Backspace')
    await expect(rows).toHaveCount(3, { timeout: 10_000 })
    await s.pause(800)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(rows).toHaveCount(3, { timeout: 30_000 })
    await s.pause(1400)

    await s.click(main.getByRole('button', { name: new RegExp(`^Actions for “${PAPERS.backrefs.title}`) }))
    await s.click(page.getByRole('menuitem', { name: 'Edit details' }))
    const dialog = page.getByRole('dialog', { name: 'Edit details' })
    await expect(dialog).toBeVisible()
    await s.pause(900)
    await s.recorder.type(dialog.getByRole('textbox', { name: 'Venue' }), 'USENIX Security Symposium 2026', {
      delay: 45,
      clear: true,
    })
    await s.pause(600)
    await s.click(dialog.getByRole('button', { name: 'Save details' }))
    await expect(page.getByText('Details saved')).toBeVisible({ timeout: 10_000 })
    await s.pause(1800)

    await s.click(page.getByRole('button', { name: 'Find papers and chats' }))
    const palette = page.getByRole('dialog', { name: 'Find papers and chats' })
    await expect(palette).toBeVisible()
    await s.keys('limitations', 80)
    await s.pause(900)
    // The palette matches loosely, so pick the conversation itself rather than whatever ranks first.
    await s.click(palette.getByRole('option', { name: /What are the major limitations/ }))
    await page.waitForURL(/\/chats\/[0-9a-f-]{36}$/, { timeout: 20_000 })
    await expect(page.getByRole('article', { name: 'Your message' }).first()).toBeVisible({ timeout: 20_000 })
    await s.pause(2000)
  },
}
