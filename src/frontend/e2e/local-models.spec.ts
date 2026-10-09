import { expect, test, type APIRequestContext } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const modelKey = 'ifm-k2-horizon-7b'
const modelName = 'IFM K2 Horizon 7B'

async function readyPaper(request: APIRequestContext) {
  const saved = await request.post('/api/v1/papers', { data: { provider: 'openalex', external_id: 'W123456789' } })
  expect(saved.ok()).toBeTruthy()
  const paper = await saved.json()
  if (paper.document_status !== 'ready') {
    const buffer = await readFile(process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf')
    const upload = await request.post('/api/v1/documents', { multipart: { file: { name: 'research.pdf', mimeType: 'application/pdf', buffer }, paper_id: paper.id, request_id: crypto.randomUUID() } })
    expect(upload.ok()).toBeTruthy()
    await expect.poll(async () => (await (await request.get(`/api/v1/papers/${paper.id}`)).json()).document_status, { timeout: 45_000 }).toBe('ready')
  }
  return paper
}

async function installation(request: APIRequestContext) {
  const response = await request.get('/api/v1/models')
  expect(response.ok()).toBeTruthy()
  return (await response.json()).items.find((model: { key: string }) => model.key === modelKey)?.installation
}

test.beforeEach(async ({ request }) => {
  // Only this isolated fixture installation is modified. Existing papers/history stay intact.
  let current = await installation(request)
  if (current?.state === 'pausing') {
    await expect.poll(async () => (await installation(request))?.state).toBe('paused')
    current = await installation(request)
  }
  if (current?.state === 'paused') {
    const resume = await request.post(`/api/v1/jobs/${current.job_id}/resume`, { data: { request_id: crypto.randomUUID() } })
    expect(resume.ok()).toBeTruthy()
    current = await installation(request)
  }
  if (current && ['queued', 'downloading', 'verifying', 'deleting'].includes(current.state)) {
    await expect.poll(async () => ['ready', 'failed', 'missing'].includes((await installation(request))?.state), { timeout: 45_000 }).toBe(true)
    current = await installation(request)
  }
  if (current?.weights_present || current?.state === 'failed') {
    const deletion = await request.delete(`/api/v1/models/${modelKey}/installation`, { headers: { 'Idempotency-Key': crypto.randomUUID() } })
    expect(deletion.ok()).toBeTruthy()
    await expect.poll(async () => (await installation(request))?.state).toBe('missing')
  }
  const saved = await request.put('/api/v1/settings', { data: { default_model: 'gpt-5.6-luna', reasoning_effort: 'low' } })
  expect(saved.ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await request.put('/api/v1/settings', { data: { default_model: 'gpt-5.6-luna', reasoning_effort: 'low' } })
})

test('E2E-09 Given missing weights, when downloading and leaving the browser page, then durable progress completes independently', async ({ page, context, request }) => {
  await page.goto('/settings')
  await expect(page.getByRole('radio', { name: modelName, exact: true })).toBeDisabled()
  await page.getByRole('button', { name: `Download ${modelName}`, exact: true }).click()
  await expect.poll(async () => (await installation(request))?.completed_bytes).toBeGreaterThan(0)
  await page.getByRole('link', { name: 'Library', exact: true }).click()
  await expect(page).toHaveURL(/\/library$/)
  await page.close()
  const returning = await context.newPage()
  await returning.goto('/settings#local-models')
  await expect(returning.getByRole('region', { name: `Manage ${modelName}` })).toBeVisible()
  await expect(returning.getByRole('radio', { name: modelName, exact: true })).toBeEnabled({ timeout: 45_000 })
  await returning.reload()
  await expect(returning.getByRole('button', { name: `Delete ${modelName} weights`, exact: true })).toBeVisible()
  expect((await (await request.get('/api/v1/settings')).json()).default_model).toBe('gpt-5.6-luna')
})

test('E2E-10 Given an active download, when paused and reloaded, then progress stays paused until resume', async ({ page, request }) => {
  await page.goto('/settings')
  await page.getByRole('button', { name: `Download ${modelName}`, exact: true }).click()
  await expect.poll(async () => (await installation(request))?.state).toBe('downloading')
  await page.getByRole('button', { name: `Pause ${modelName} download`, exact: true }).click()
  await expect.poll(async () => (await installation(request))?.state).toBe('paused')
  const bytes = (await installation(request)).completed_bytes
  await page.reload()
  await expect(page.getByRole('button', { name: `Resume ${modelName} download`, exact: true })).toBeVisible()
  expect((await installation(request)).completed_bytes).toBe(bytes)
  await page.getByRole('link', { name: 'Activity', exact: true }).click()
  const modelLink = page.getByRole('list', { name: 'Jobs' }).getByRole('link', { name: modelName, exact: true }).first()
  await expect(modelLink).toBeVisible()
  await modelLink.click()
  await expect(page.getByRole('heading', { name: 'Local models', exact: true })).toBeInViewport()
  await page.getByRole('button', { name: `Resume ${modelName} download`, exact: true }).click()
  await expect(page.getByRole('radio', { name: modelName, exact: true })).toBeEnabled({ timeout: 45_000 })
})

test('E2E-11 Given a local default, when its weights are deleted, then the saved default survives and generation stays blocked', async ({ page, request }) => {
  const paper = await readyPaper(request)
  await page.goto('/settings')
  await page.getByRole('button', { name: `Download ${modelName}`, exact: true }).click()
  const choice = page.getByRole('radio', { name: modelName, exact: true })
  await expect(choice).toBeEnabled({ timeout: 45_000 })
  await choice.check()
  await page.getByRole('button', { name: 'Save defaults', exact: true }).click()
  await expect(page.getByText('Model defaults saved.')).toBeVisible()
  await page.getByRole('button', { name: `Delete ${modelName} weights`, exact: true }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText('saved default')
  await dialog.getByRole('button', { name: 'Delete weights', exact: true }).click()
  await expect(choice).toBeDisabled()
  await expect(choice).toBeChecked()
  await page.reload()
  await expect(choice).toBeDisabled()
  await expect(choice).toBeChecked()
  expect((await (await request.get('/api/v1/settings')).json()).default_model).toBe(modelKey)
  await page.goto(`/papers/${paper.id}`)
  await page.getByRole('textbox', { name: 'Question about this paper' }).fill('What dataset is used?')
  await expect(page.getByRole('button', { name: 'Ask question', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: /^Model: IFM K2 Horizon 7B/ }).click()
  const missing = page.getByRole('menuitemradio', { name: /IFM K2 Horizon 7B/ })
  await expect(missing).toHaveAttribute('aria-disabled', 'true')
  await expect(missing).toHaveAttribute('aria-checked', 'true')
})

test('E2E-12 Given verified local weights, when summarizing and asking a paper, then grounded responses persist with the local model', async ({ page, request }) => {
  const paper = await readyPaper(request)
  await page.goto('/settings')
  await page.getByRole('button', { name: `Download ${modelName}`, exact: true }).click()
  const choice = page.getByRole('radio', { name: modelName, exact: true })
  await expect(choice).toBeEnabled({ timeout: 45_000 })
  await choice.check()
  const efforts = page.getByRole('radiogroup', { name: 'Reasoning effort' })
  await expect(efforts.getByRole('radio', { name: 'On', exact: true })).toBeVisible()
  await efforts.getByRole('radio', { name: 'Low', exact: true }).click()
  await page.getByRole('button', { name: 'Save defaults', exact: true }).click()
  await expect(page.getByText('Model defaults saved.')).toBeVisible()
  expect((await (await request.get('/api/v1/settings')).json()).reasoning_effort).toBe('low')
  await page.goto(`/papers/${paper.id}`)
  const summary = page.getByRole('article', { name: 'Paper summary' })
  const versions = summary.getByRole('button', { name: /^Version \d+ of \d+$/ })
  await expect(summary.getByRole('button', { name: 'Generate summary', exact: true }).or(versions)).toBeVisible()
  const before = await versions.isVisible() ? Number((await versions.innerText()).match(/of (\d+)/)?.[1]) : 0
  if (before) {
    await versions.click()
    await page.getByRole('menuitem', { name: 'Generate summary', exact: true }).click()
  } else await summary.getByRole('button', { name: 'Generate summary', exact: true }).click()
  await expect(summary.getByRole('button', { name: `Version ${before + 1} of ${before + 1}` })).toBeVisible({ timeout: 45_000 })
  await expect(summary).toContainText('Orion-12')
  const summaries = await (await request.get(`/api/v1/papers/${paper.id}/summaries`)).json()
  expect(summaries.items[0].model).toBe(modelKey)
  expect(summaries.items[0].reasoning_effort).toBe('low')
  await page.getByRole('button', { name: /^Model: IFM K2 Horizon 7B, Low reasoning/ }).click()
  await page.getByRole('menuitem', { name: /Reasoning effort/ }).hover()
  await page.getByRole('menuitemradio', { name: 'Medium', exact: true }).click()
  await page.getByRole('textbox', { name: 'Question about this paper' }).fill('What dataset is used?')
  await page.getByRole('button', { name: 'Ask question', exact: true }).click()
  const answer = page.getByRole('article', { name: 'Assistant message' }).last()
  await expect(answer).toContainText('Orion-12', { timeout: 45_000 })
  await expect(answer.getByRole('button', { name: /^Source, page \d+$/ }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Stop generation' })).toBeHidden()
  await expect(answer).not.toContainText('Synthetic reasoning fixture')
  const chatId = page.url().split('/').at(-1)
  const messages = await (await request.get(`/api/v1/chats/${chatId}/messages`)).json()
  expect(messages.items.at(-1).model).toBe(modelKey)
  expect(messages.items.at(-1).reasoning_effort).toBe('medium')
  expect(messages.items.at(-1).content).toContain('[source:')
  expect(messages.items.at(-1).content).not.toContain('【source:')
  await expect(answer).not.toContainText(messages.items.at(-1).citations[0].chunk_id)
  await page.reload()
  await expect(answer).toContainText('Orion-12')
})
