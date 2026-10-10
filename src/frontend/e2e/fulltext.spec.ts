import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// ARA-087: PDFs come only from OpenAlex's stored copies (the fixture's content endpoint and signed storage);
// otherwise the workspace offers the DOI link and an upload. Saving starts retrieval without a click (ARA-084).
const api = '/api/v1'

async function saved(request: APIRequestContext, id: string) {
  const response = await request.post(`${api}/papers`, { data: { provider: id.startsWith('W') ? 'openalex' : 'semantic_scholar', external_id: id } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id as string
}
const firstPage = (page: Page) => page.getByRole('group', { name: 'Page 1', exact: true }).locator('canvas')
// The reader has no PDF/Details tabs any more (ARA-097); on desktop it is always beside the conversation.
const reader = (page: Page) => page.getByRole('region', { name: 'PDF reader', exact: true })

test('Given stored OpenAlex copies, When saved, Then real PDF pages open and a summary follows without a click', async ({ page, request }) => {
  for (const id of ['W19001', 's2-fulltext-doi']) {
    const paperId = await saved(request, id)
    await page.goto(`/papers/${paperId}`)
    await expect(firstPage(page)).toBeVisible({ timeout: 45_000 })
    if (id === 'W19001') {
      const summary = page.getByRole('article', { name: 'Paper summary' })
      await expect(summary.getByRole('button', { name: /^(Show full|Collapse) summary$/ })).toBeVisible({ timeout: 45_000 })
    }
    await page.reload()
    await expect(firstPage(page)).toBeVisible()
    const status = await (await request.get(`${api}/papers/${paperId}/fulltext`)).json()
    expect(status.acquisition).toMatchObject({ provider: 'openalex', source: 'content' })
  }
})

test('Given OpenAlex limits requests, When its wait has passed, Then a deliberate retry downloads the PDF', async ({ page, request }) => {
  const paperId = await saved(request, 'W19003')
  await page.goto(`/papers/${paperId}`)
  await expect(reader(page).getByText('OpenAlex is limiting requests', { exact: true })).toBeVisible({ timeout: 45_000 })
  await expect(reader(page).getByRole('link', { name: 'Open the paper', exact: true })).toHaveAttribute('href', 'https://doi.org/10.5555/fulltext-limited')
  const grant = await request.post(`${api}/__fixtures/fulltext/fulltext-limited/grant`)
  expect(grant.ok()).toBeTruthy()
  // A failed attempt is never restarted by itself; trying again is a click once the reported wait passes.
  const retry = reader(page).getByRole('button', { name: 'Try again', exact: true })
  await expect(retry).toBeEnabled({ timeout: 10_000 })
  await retry.click()
  await expect(firstPage(page)).toBeVisible({ timeout: 45_000 })
})

test('Given a spent OpenAlex allowance, Then the reset wait is shown in hours', async ({ page, request }) => {
  const paperId = await saved(request, 'W19005')
  await page.goto(`/papers/${paperId}`)
  await expect(reader(page).getByText(/Today.s OpenAlex allowance is used up/)).toBeVisible({ timeout: 45_000 })
  await expect(reader(page).getByText('Try again in 1 hour.', { exact: true })).toBeVisible()
  await expect(reader(page).getByRole('button', { name: 'Try again', exact: true })).toBeDisabled()
})

test('Given an unusable or unsafe OpenAlex link, Then the DOI link and upload remain', async ({ page, request }) => {
  for (const [id, message] of [['W19004', 'OpenAlex’s copy isn’t a usable PDF'], ['W19006', 'OpenAlex’s link couldn’t be followed safely']]) {
    const paperId = await saved(request, id)
    await page.goto(`/papers/${paperId}`)
    await expect(reader(page).getByText(message, { exact: true })).toBeVisible({ timeout: 45_000 })
    await expect(reader(page).getByRole('link', { name: 'Open the paper', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Upload PDF', exact: true })).toBeVisible()
    await expect(page.getByText(/paywall/i)).toHaveCount(0)
  }
})

test('Given no stored copy at 390px, Then the DOI link and keyboard upload remain usable', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const id of ['W19007', 's2-fulltext-semantic']) {
    const paperId = await saved(request, id)
    await page.goto(`/papers/${paperId}?view=pdf`)
    await expect(reader(page).getByText('OpenAlex doesn’t have this PDF', { exact: true })).toBeVisible({ timeout: 45_000 })
    await expect(reader(page).getByRole('link', { name: 'Open the paper', exact: true })).toHaveAttribute('target', '_blank')
    // Nothing more can be found by trying again; upload is the way forward.
    await expect(reader(page).getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0)
  }
  const upload = page.getByRole('button', { name: 'Upload PDF', exact: true })
  await upload.focus()
  const picker = page.waitForEvent('filechooser')
  await page.keyboard.press('Enter')
  expect((await picker).isMultiple()).toBe(false)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
