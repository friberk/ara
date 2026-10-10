import { expect } from 'playwright/test'

import { home } from '../lib/ui.mjs'

// Settings: theme, default model and reasoning, and library and search options. Nothing is changed for good.
export default {
  id: '09-settings',
  async run(s) {
    const { page } = s
    await s.go('/', home(page))
    await s.click(page.getByRole('button', { name: 'Settings', exact: true }))
    const dialog = page.getByRole('dialog', { name: 'Settings' })
    await expect(dialog).toBeVisible()
    await s.pause(1000)

    await s.click(dialog.getByRole('radio', { name: 'Dark' }))
    await s.pause(1500)
    await s.click(dialog.getByRole('radio', { name: 'Light' }))
    await s.pause(900)

    await s.click(dialog.getByRole('tab', { name: 'Models', exact: true }))
    await s.pause(2600)
    await s.click(dialog.getByRole('tab', { name: 'Library and search', exact: true }))
    await s.pause(1400)
    const details = dialog.getByText('Paper details', { exact: true }).first()
    if (await details.isVisible()) await s.hover(details, 1800)

    await s.click(dialog.getByRole('button', { name: 'Close' }).first())
    await expect(dialog).toBeHidden()
    await s.pause(800)
  },
}
