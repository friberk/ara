import { expect, test, type APIRequestContext } from '@playwright/test'

const api = '/api/v1'

async function saved(request: APIRequestContext, id: string) {
  const response = await request.post(`${api}/papers`, { data: { provider: id.startsWith('W') ? 'openalex' : 'semantic_scholar', external_id: id } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id as string
}

// ARA-084: saving a paper that lists a PDF or has a DOI retrieves it without a click.
const manualRetrieval = /^(Get|Find) PDF$/

test('Given OpenAlex and Semantic Scholar copies, When saved, Then real PDF pages open and a summary follows without a click', async ({ page, request }) => {
  for (const id of ['W19001', 's2-fulltext-doi', 's2-fulltext-semantic']) {
    const paperId = await saved(request, id)
    await page.goto(`/papers/${paperId}`)
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await expect(page.getByRole('button', { name: manualRetrieval })).toHaveCount(0)
    await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible({ timeout: 45_000 })
    if (id === 'W19001') {
      const summary = page.getByRole('article', { name: 'Paper summary' })
      await expect(summary.getByRole('button', { name: 'Version 1 of 1', exact: true })).toBeVisible({ timeout: 45_000 })
    }
    await page.reload()
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible()
    const status = await (await request.get(`${api}/papers/${paperId}/fulltext`)).json()
    expect(status.acquisition.provider).toBe(id === 's2-fulltext-semantic' ? 'semantic_scholar' : 'openalex')
  }
})

test('Given blocked access, When it changes, Then a fresh retry succeeds after refresh', async ({ page, request }) => {
  const paperId = await saved(request, 'W19003')
  await page.goto(`/papers/${paperId}`)
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await expect(page.getByRole('tabpanel', { name: 'PDF', exact: true }).getByText('The source blocked the download')).toBeVisible({ timeout: 45_000 })
  await expect(page.getByRole('link', { name: 'Open publisher', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  // A failed automatic attempt is never restarted by itself; trying again is a deliberate click.
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeVisible()
  const grant = await request.post(`${api}/__fixtures/fulltext/fulltext-denied/grant`)
  expect(grant.ok()).toBeTruthy()
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible({ timeout: 45_000 })
})

test('Given HTML instead of PDF, Then browser and upload fallback stay available', async ({ page, request }) => {
  const paperId = await saved(request, 'W19004')
  await page.goto(`/papers/${paperId}`)
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await expect(page.getByRole('tabpanel', { name: 'PDF', exact: true }).getByText(/return a usable PDF/)).toBeVisible({ timeout: 45_000 })
  await expect(page.getByRole('link', { name: 'Open PDF in browser', exact: true })).toHaveAttribute('target', '_blank')
  await expect(page.getByRole('button', { name: 'Upload PDF', exact: true })).toBeVisible()
  await expect(page.getByText(/paywall/i)).toHaveCount(0)
})

test('Given a paper without PDF links at 390px, Then discovery runs by itself and keyboard upload remains usable', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const paperId = await saved(request, 'W19007')
  await page.goto(`/papers/${paperId}?view=pdf`)
  await expect(page.getByRole('tabpanel', { name: 'PDF', exact: true }).getByText('No open PDF was found')).toBeVisible({ timeout: 45_000 })
  // Both providers answered, so trying again could not find more; upload is the way forward.
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0)
  const upload = page.getByRole('button', { name: 'Upload PDF', exact: true })
  await upload.focus()
  const picker = page.waitForEvent('filechooser')
  await page.keyboard.press('Enter')
  expect((await picker).isMultiple()).toBe(false)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('link', { name: 'Open Semantic Scholar', exact: true })).toHaveAttribute('target', '_blank')
})
