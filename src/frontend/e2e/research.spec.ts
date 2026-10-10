import { expect, test, type Page } from '@playwright/test'

// Runs against the isolated fixture stack (tests/fixtures/server.py): both providers return the same
// synthetic paper with the same DOI, so saving it from one provider marks it saved for the other.
const title = 'Traceable Research Systems'
const providers = [{ value: 'openalex', label: 'OpenAlex' }, { value: 'semantic_scholar', label: 'Semantic Scholar' }] as const

function result(page: Page) { return page.getByRole('article', { name: title }) }

test('E2E-01 Given each provider, when a topic is searched, then normalized papers appear', async ({ page }) => {
  await page.goto('/search')
  for (const provider of providers) {
    await page.getByRole('textbox', { name: 'Research topic' }).fill('research')
    await page.getByRole('button', { name: /^Academic provider:/ }).click()
    await page.getByRole('menuitemradio', { name: new RegExp(`^${provider.label}`) }).click()
    await expect(page.getByRole('button', { name: `Academic provider: ${provider.label}` })).toBeVisible()
    await page.getByRole('button', { name: 'Search papers', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`[?&]provider=${provider.value}`))
    await expect(page.getByRole('heading', { level: 1, name: 'research' })).toBeVisible()
    await expect(result(page).getByRole('heading', { level: 2, name: title })).toBeVisible()
    await expect(result(page).getByText('Ada Researcher')).toBeVisible()
    await expect(result(page).getByText('2024')).toBeVisible()
    await expect(result(page).getByRole('link', { name: /10\.5555\/cs593\.fixture/ })).toHaveAttribute('href', 'https://doi.org/10.5555/cs593.fixture')
  }
})

test('E2E-02 Given a search result, when saved and refreshed, then it stays in the library once', async ({ page }) => {
  await page.goto('/search?q=research&provider=openalex')
  await result(page).getByRole('button', { name: 'Save to library' }).click()
  await expect(page.getByText('Saved to library')).toBeVisible()
  await expect(result(page).getByText('In library')).toBeVisible()
  await expect(result(page).getByRole('link', { name: 'Open paper' })).toHaveAttribute('href', /^\/papers\/[0-9a-f-]{36}$/)

  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Library', exact: true }).click()
  const main = page.getByRole('main')
  await expect(main.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible()
  await expect(main.getByRole('link', { name: title, exact: true })).toBeVisible()
  await page.reload()
  await expect(main.getByRole('link', { name: title, exact: true })).toBeVisible()

  // The same DOI from the other provider is already saved: no second save, no duplicate row.
  await page.goto('/search?q=research&provider=semantic_scholar')
  await expect(result(page).getByText('In library')).toBeVisible()
  await expect(result(page).getByRole('button', { name: 'Save to library' })).toHaveCount(0)
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Library', exact: true }).click()
  await expect(main.getByRole('link', { name: title, exact: true })).toHaveCount(1)
})

test('Mobile shell stays usable at 390px with the sidebar, skip link and no horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/search?q=research&provider=openalex')
  await expect(result(page)).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: 'Toggle Sidebar' }).click()
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeHidden()
  for (const path of ['/', '/library', '/settings']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `no horizontal scroll on ${path}`).toBeTruthy()
  }
})
