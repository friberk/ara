import { screen, waitFor, within } from '@testing-library/react'
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

const localMissing = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', status: 'unavailable', reasoning_efforts: ['default'], unavailable_reason: 'Download weights in Settings to use this model.', unavailable_code: 'MODEL_WEIGHTS_MISSING', installation: { state: 'missing', weights_present: false, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 0, total_bytes: 5592218900, job_id: null, digest: null, updated_at: null, error: null } }

test('Given missing local weights, When explored by keyboard, Then the explanation is discoverable and selection is guarded', async () => {
  mockApi({ 'GET /models': { items: [luna, localMissing] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  const item = await screen.findByRole('menuitemradio', { name: /K2 Horizon 7B/ })
  expect(item).toHaveTextContent(/Download weights/)
  await user.keyboard('{Home}{ArrowDown}')
  expect(item).toHaveFocus()
  await user.keyboard('{Enter}')
  expect(screen.getByLabelText('Selection')).toHaveTextContent('gpt-5.6-luna/low')
  expect(item).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('menuitem', { name: 'Model settings' })).toHaveAttribute('href', '/settings#local-models')
})

test('Given deleted default weights, Then the selected model remains visible and no hosted model replaces it', async () => {
  mockApi({ 'GET /models': { items: [luna, localMissing] }, 'GET /settings': { default_model: localMissing.key, reasoning_effort: 'default' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: K2 Horizon 7B/ }))
  expect(screen.getByLabelText('Selection')).toHaveTextContent('ifm-k2-horizon-7b/default')
  expect(screen.getByRole('menuitemradio', { name: /K2 Horizon 7B/ })).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByRole('menuitemradio', { name: /K2 Horizon 7B/ })).toHaveTextContent(/Download weights/)
})

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

test('Given saving the default fails, Then the menu stays open and explains the error inline', async () => {
  // Errors stay inline (DESIGN.md: toasts are for success only).
  mockApi({ 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'PUT /settings': () => new Response(JSON.stringify({ code: 'SETTINGS_UNAVAILABLE', message: 'Settings could not be saved. Try again.' }), { status: 503, headers: { 'Content-Type': 'application/json' } }) })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  await chooseEffort(user, 'High')
  await user.click(screen.getByRole('button', { name: 'Model: GPT-5.6 Luna, High reasoning' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Set as default' }))
  const menu = await screen.findByRole('menu')
  expect(await within(menu).findByRole('alert')).toHaveTextContent('Settings could not be saved. Try again.')
})
