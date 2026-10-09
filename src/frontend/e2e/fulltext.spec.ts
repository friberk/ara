import { expect, test, type APIRequestContext } from '@playwright/test'

const api = '/api/v1'

async function saved(request: APIRequestContext, id: string) {
  const response = await request.post(`${api}/papers`, { data: { provider: id.startsWith('W') ? 'openalex' : 'semantic_scholar', external_id: id } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id as string
}

test('Given OpenAlex and Semantic Scholar copies, When retrieved, Then real PDF pages open', async ({ page, request }) => {
  for (const id of ['W19001', 's2-fulltext-doi', 's2-fulltext-semantic']) {
    const paperId = await saved(request, id)
    await page.goto(`/papers/${paperId}`)
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await page.getByRole('button', { name: /^(Get|Find) PDF$/ }).click()
    await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible({ timeout: 45_000 })
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
  await page.getByRole('button', { name: /^(Get|Find) PDF$/ }).click()
  await expect(page.getByRole('tabpanel', { name: 'PDF', exact: true }).getByText(/This site blocked the download/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open publisher', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry download', exact: true })).toBeVisible()
  const grant = await request.post(`${api}/__fixtures/fulltext/fulltext-denied/grant`)
  expect(grant.ok()).toBeTruthy()
  await page.getByRole('button', { name: 'Retry download', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible({ timeout: 45_000 })
})

test('Given HTML instead of PDF, Then browser and upload fallback stay available', async ({ page, request }) => {
  const paperId = await saved(request, 'W19004')
  await page.goto(`/papers/${paperId}`)
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await page.getByRole('button', { name: /^(Get|Find) PDF$/ }).click()
  await expect(page.getByRole('tabpanel', { name: 'PDF', exact: true }).getByText(/web page instead of a PDF/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Upload PDF', exact: true })).toBeVisible()
  await expect(page.getByText(/paywall/i)).toHaveCount(0)
})

test('Given a paper without PDF links at 390px, Then discovery, retry and keyboard upload remain usable', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const paperId = await saved(request, 'W19007')
  await page.goto(`/papers/${paperId}?view=pdf`)
  await page.getByRole('button', { name: /^(Find PDF|Retry download)$/ }).click()
  await expect(page.getByRole('tabpanel', { name: 'PDF', exact: true }).getByText(/No direct PDF link was found/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry download', exact: true })).toBeEnabled()
  const upload = page.getByRole('button', { name: 'Upload PDF', exact: true })
  await upload.focus()
  const picker = page.waitForEvent('filechooser')
  await page.keyboard.press('Enter')
  expect((await picker).isMultiple()).toBe(false)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('link', { name: 'Open Semantic Scholar', exact: true })).toHaveAttribute('target', '_blank')
})
