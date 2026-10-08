import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'
import { TooltipProvider } from '@/components/ui/tooltip'
import { GenerationSettingsProvider } from './generation-settings'
import { useGenerationSettings } from './generation-settings-context'
import { ModelSwitcher } from './ModelSwitcher'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const unavailable = { ...luna, key: 'unavailable-exact', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [] }
afterEach(() => vi.unstubAllGlobals())

function Selection() { const { settings } = useGenerationSettings(); return <output aria-label="Selection">{`${settings.model}/${settings.reasoning_effort}`}</output> }
// Submenus are driven by keyboard: jsdom pointer events do not follow Radix's submenu pointer grace.
async function chooseEffort(user: ReturnType<typeof renderWithProviders>['user'], label: string) {
  screen.getByRole('menuitem', { name: /Reasoning effort/ }).focus()
  await user.keyboard('{ArrowRight}')
  const option = await screen.findByRole('menuitemradio', { name: label })
  option.focus()
  await user.keyboard('{Enter}')
}
function mount() {
  return renderWithProviders(<TooltipProvider><GenerationSettingsProvider><ModelSwitcher purpose="chat" /><Selection /></GenerationSettingsProvider></TooltipProvider>)
}

test('Given unavailable and supported models, Then exact IDs and reasoning capabilities govern selection', async () => {
  mockApi({ 'GET /models': { items: [luna, unavailable] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  const trigger = await screen.findByRole('button', { name: 'Model: GPT-5.6 Luna, Low reasoning' })
  await user.click(trigger)
  expect(await screen.findByRole('menuitemradio', { name: /Unavailable model/ })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('menuitemradio', { name: /GPT-5.6 Luna/ })).toHaveAttribute('aria-checked', 'true')
  await chooseEffort(user, 'High')
  expect(screen.getByLabelText('Selection')).toHaveTextContent('gpt-5.6-luna/high')
})

test('Given a changed selection, When Set as default is chosen, Then the exact model and effort are saved', async () => {
  const { calls } = mockApi({ 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'PUT /settings': { default_model: luna.key, reasoning_effort: 'high' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  expect(screen.getByRole('menuitem', { name: 'Default model' })).toHaveAttribute('aria-disabled', 'true')
  await chooseEffort(user, 'High')
  await user.click(screen.getByRole('button', { name: 'Model: GPT-5.6 Luna, High reasoning' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Set as default' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ default_model: luna.key, reasoning_effort: 'high' }))
})

test('Given a model that cannot stream, When choosing a chat model, Then it is disabled with the reason', async () => {
  const batch = { ...luna, key: 'batch-only', model_id: 'batch-only', display_name: 'Batch model', supports_streaming: false }
  mockApi({ 'GET /models': { items: [luna, batch] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  const item = await screen.findByRole('menuitemradio', { name: /Batch model/ })
  expect(item).toHaveAttribute('aria-disabled', 'true')
  expect(item).toHaveTextContent('Cannot stream answers')
})

test('Given another model is chosen, Then an effort it does not support is replaced by its first effort', async () => {
  const terra = { ...luna, key: 'gpt-5.6-terra', model_id: 'gpt-5.6-terra', display_name: 'GPT-5.6 Terra', reasoning_efforts: ['medium', 'xhigh'] }
  mockApi({ 'GET /models': { items: [luna, terra] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  await user.click(await screen.findByRole('menuitemradio', { name: /GPT-5.6 Terra/ }))
  expect(screen.getByLabelText('Selection')).toHaveTextContent('gpt-5.6-terra/medium')
  expect(screen.getByRole('button', { name: 'Model: GPT-5.6 Terra, Medium reasoning' })).toBeVisible()
})

test('Given models are still loading, Then the switcher is disabled and says so', async () => {
  mockApi({ 'GET /models': () => new Promise<Response>(() => {}), 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  mount()
  expect(await screen.findByRole('button', { name: 'Model: Loading models' })).toBeDisabled()
})
