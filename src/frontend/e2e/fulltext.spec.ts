import { expect, test, type APIRequestContext } from '@playwright/test'

const api = 'http://127.0.0.1:8002/api/v1'

async function saved(request: APIRequestContext, id: string) {
  const response = await request.post(`${api}/papers`, { data: { provider: id.startsWith('W') ? 'openalex' : 'semantic_scholar', external_id: id } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id as string
}

test('Given OpenAlex and Semantic Scholar copies, When retrieved, Then real PDF pages open', async ({ page, request }) => {
  for (const id of ['W19001', 's2-fulltext-doi']) {
    const paperId = await saved(request, id)
    await page.goto(`/papers/${paperId}`)
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await page.getByRole('button', { name: /^(Get|Find) PDF$/ }).click()
    await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible({ timeout: 45_000 })
    await page.reload()
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible()
  }
})

test('Given blocked access, When it changes, Then a fresh retry succeeds after refresh', async ({ page, request }) => {
  const paperId = await saved(request, 'W19003')
  await page.goto(`/papers/${paperId}`)
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await page.getByRole('button', { name: /^(Get|Find) PDF$/ }).click()
  await expect(page.getByText(/This site blocked the download/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open publisher', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry download', exact: true })).toBeVisible()
  const grant = await request.post('http://127.0.0.1:8002/__fixtures/fulltext/fulltext-denied/grant')
  expect(grant.ok()).toBeTruthy()
  await page.getByRole('button', { name: 'Retry download', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')).toBeVisible({ timeout: 45_000 })
})

test('Given HTML instead of PDF, Then browser and upload fallback stay available', async ({ page, request }) => {
  const paperId = await saved(request, 'W19004')
  await page.goto(`/papers/${paperId}`)
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await page.getByRole('button', { name: /^(Get|Find) PDF$/ }).click()
  await expect(page.getByText(/web page instead of a PDF/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Upload PDF', exact: true })).toBeVisible()
  await expect(page.getByText(/paywall/i)).toHaveCount(0)
})
