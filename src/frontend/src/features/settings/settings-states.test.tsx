// Test-after coverage (ARA-038), moved to the Settings dialog (ARA-109). Each test was checked
// against a deliberate mutation of the implementation to confirm it can fail.
import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const settings = { default_model: luna.key, reasoning_effort: 'low' }
afterEach(() => vi.unstubAllGlobals())

test('Given no models on the server, Then Models says so and how to fix it', async () => {
  mockApi({ 'GET /models': { items: [] }, 'GET /settings': settings })
  renderApp('/?settings=models')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  expect(await within(dialog).findByRole('heading', { name: 'No models are set up' })).toBeVisible()
  expect(within(dialog).getByText('The server lists no models. Check its configuration, then reopen Settings.')).toBeVisible()
  expect(within(dialog).queryByRole('radiogroup', { name: 'Default model' })).not.toBeInTheDocument()
})

test('Given models are loading, Then a loading state is announced', async () => {
  mockApi({ 'GET /models': () => new Promise<Response>(() => {}), 'GET /settings': settings })
  renderApp('/?settings=models')
  await waitFor(() => expect(screen.getAllByRole('status').some((element) => element.textContent?.includes('Loading models…'))).toBe(true))
})

test('Given models cannot load, Then the error is shown inline and Try again reloads them', async () => {
  // Fail every request until the user retries: the shell's model switcher shares this query and may refetch on its own.
  let failing = true
  const { calls } = mockApi({
    'GET /models': () => (failing ? json({ code: 'UPSTREAM_UNAVAILABLE', message: 'Model list is unavailable right now.', request_id: 'r1' }, 502) : json({ items: [luna] })),
    'GET /settings': settings,
  })
  const { user } = renderApp('/?settings=models')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  const alert = await within(dialog).findByRole('alert')
  expect(alert).toHaveTextContent('Model list is unavailable right now.')
  failing = false
  await user.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(await within(await within(dialog).findByRole('radiogroup', { name: 'Default model' })).findByRole('radio', { name: 'GPT-5.6 Luna' })).toBeChecked()
  expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument()
  expect(calls.filter((call) => call.path === '/models').length).toBeGreaterThanOrEqual(2)
})
