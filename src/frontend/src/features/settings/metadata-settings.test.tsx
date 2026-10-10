// Where paper details come from (ARA-086, ARA-109): OpenAlex by default, Semantic Scholar on request.
import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

afterEach(() => vi.unstubAllGlobals())

test('Given no saved choice, Then Library and search shows OpenAlex as where paper details come from, and what each catalog is', async () => {
  mockApi({ 'GET /metadata/settings': { source: 'openalex' } })
  renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Paper details' })
  const choices = await within(section).findByRole('radiogroup', { name: 'Paper details' })
  await waitFor(() => expect(within(choices).getByRole('radio', { name: 'OpenAlex' })).toBeChecked())
  expect(within(choices).getByRole('radio', { name: 'Semantic Scholar' })).not.toBeChecked()
  expect(within(choices).getByRole('radio', { name: 'OpenAlex' })).toHaveAccessibleDescription('A free, open catalog of research from every field, run by the nonprofit OurResearch.')
  expect(within(choices).getByRole('radio', { name: 'Semantic Scholar' })).toHaveAccessibleDescription('A free research catalog run by the Allen Institute for AI.')
  expect(within(section).getByText(/Details you edited are never replaced\./)).toBeVisible()
  expect(within(section).getByText(/If a paper’s details come back wrong, try the other catalog\./)).toBeVisible()
})

test('Given OpenAlex, When Semantic Scholar is picked, Then the choice is saved at once and stays chosen', async () => {
  let saved = { source: 'openalex' }
  const { calls } = mockApi({ 'GET /metadata/settings': () => json(saved), 'PUT /metadata/settings': ({ body }) => json(saved = body as typeof saved) })
  const { user } = renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Paper details' })
  await waitFor(() => expect(within(section).getByRole('radio', { name: 'OpenAlex' })).toBeChecked())
  await user.click(within(section).getByRole('radio', { name: 'Semantic Scholar' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT' && call.path === '/metadata/settings')?.body).toEqual({ source: 'semantic_scholar' }))
  expect(await within(section).findByText('Saved')).toBeVisible()
  expect(within(section).getByRole('radio', { name: 'Semantic Scholar' })).toBeChecked()
})

test('Given the save fails, Then the saved choice stays selected and the error is shown', async () => {
  mockApi({ 'GET /metadata/settings': { source: 'openalex' }, 'PUT /metadata/settings': () => json({ code: 'INTERNAL_ERROR', message: 'An unexpected error occurred.' }, 500) })
  const { user } = renderApp('/?settings=library')
  const section = await screen.findByRole('region', { name: 'Paper details' })
  await waitFor(() => expect(within(section).getByRole('radio', { name: 'OpenAlex' })).toBeChecked())
  await user.click(within(section).getByRole('radio', { name: 'Semantic Scholar' }))
  expect(await within(section).findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
  expect(within(section).getByRole('radio', { name: 'OpenAlex' })).toBeChecked()
})
