// Metadata source for uploaded PDFs (ARA-086): OpenAlex by default, Semantic Scholar on request.
import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

afterEach(() => vi.unstubAllGlobals())

test('Given no saved choice, Then Settings shows OpenAlex as the metadata source', async () => {
  mockApi({ 'GET /metadata/settings': { source: 'openalex' } })
  renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Metadata source' })
  const choices = await within(section).findByRole('radiogroup', { name: 'Metadata source' })
  await waitFor(() => expect(within(choices).getByRole('radio', { name: 'OpenAlex' })).toHaveAttribute('aria-checked', 'true'))
  expect(within(choices).getByRole('radio', { name: 'Semantic Scholar' })).toHaveAttribute('aria-checked', 'false')
  expect(within(section).getByText(/never replaces details you edited/)).toBeVisible()
})

test('Given OpenAlex, When Semantic Scholar is picked, Then the choice is saved at once and stays chosen', async () => {
  let saved = { source: 'openalex' }
  const { calls } = mockApi({ 'GET /metadata/settings': () => json(saved), 'PUT /metadata/settings': ({ body }) => json(saved = body as typeof saved) })
  const { user } = renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Metadata source' })
  await waitFor(() => expect(within(section).getByRole('radio', { name: 'OpenAlex' })).toHaveAttribute('aria-checked', 'true'))
  await user.click(within(section).getByRole('radio', { name: 'Semantic Scholar' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/metadata/settings')?.body).toEqual({ source: 'semantic_scholar' }))
  expect(await within(section).findByText('Metadata source saved.')).toBeVisible()
  expect(within(section).getByRole('radio', { name: 'Semantic Scholar' })).toHaveAttribute('aria-checked', 'true')
})

test('Given the save fails, Then the saved choice stays selected and the error is shown', async () => {
  mockApi({ 'GET /metadata/settings': { source: 'openalex' }, 'PUT /metadata/settings': () => json({ code: 'INTERNAL_ERROR', message: 'An unexpected error occurred.' }, 500) })
  const { user } = renderApp('/settings')
  const section = await screen.findByRole('region', { name: 'Metadata source' })
  await waitFor(() => expect(within(section).getByRole('radio', { name: 'OpenAlex' })).toHaveAttribute('aria-checked', 'true'))
  await user.click(within(section).getByRole('radio', { name: 'Semantic Scholar' }))
  expect(await within(section).findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
  expect(within(section).getByRole('radio', { name: 'OpenAlex' })).toHaveAttribute('aria-checked', 'true')
})
