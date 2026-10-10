import { act, screen, waitFor, within } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'
import { TooltipProvider } from '@/components/ui/tooltip'
import { GenerationSettingsProvider } from './generation-settings'
import { useGenerationSettings } from './generation-settings-context'
import { ModelSwitcher } from './ModelSwitcher'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const unavailable = { ...luna, key: 'unavailable-exact', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [] }
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
// Local model tests run with open models on, as the server reports them (ARA-090).
const openModels = { 'GET /features': { open_models: true } }

function Selection() { const { settings } = useGenerationSettings(); return <output aria-label="Selection">{`${settings.model}/${settings.reasoning_effort}`}</output> }
// Submenus are driven by keyboard: jsdom pointer events do not follow Radix's submenu pointer grace.
async function chooseEffort(user: ReturnType<typeof renderWithProviders>['user'], label: string) {
  act(() => screen.getByRole('menuitem', { name: /Reasoning effort/ }).focus())
  await user.keyboard('{ArrowRight}')
  const option = await screen.findByRole('menuitemradio', { name: label })
  act(() => option.focus())
  await user.keyboard('{Enter}')
}
function mount() {
  return renderWithProviders(<TooltipProvider><GenerationSettingsProvider><ModelSwitcher purpose="chat" /><Selection /></GenerationSettingsProvider></TooltipProvider>)
}

test.each(['default', 'on'])('Given saved %s aliases High, Then the composer shows four explicit choices and retains default status', async (reasoning) => {
  const local = { ...luna, key: 'native-named', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' } }
  const { calls } = mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: reasoning } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: 'Model: GPT-5.6 Luna, High reasoning' }))
  act(() => screen.getByRole('menuitem', { name: /Reasoning effort/ }).focus())
  await user.keyboard('{ArrowRight}')
  const high = await screen.findByRole('menuitemradio', { name: 'High' })
  const menu = high.closest('[role="menu"]') as HTMLElement
  expect(within(menu).getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual(['None', 'Low', 'Medium', 'High'])
  expect(high).toHaveAttribute('aria-checked', 'true')
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given verified boolean-only reasoning, When toggled in the composer, Then none and on remain the exact native request values', async () => {
  const local = { ...luna, key: 'native-boolean', provider: 'ollama', reasoning_efforts: ['default', 'none', 'on'], reasoning_aliases: { default: 'none' } }
  mockApi({ 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model:/ }))
  const toggle = await screen.findByRole('menuitemcheckbox', { name: 'Reasoning' })
  expect(toggle).toHaveAttribute('aria-checked', 'false')
  expect(screen.queryByRole('menuitem', { name: /Reasoning effort/ })).not.toBeInTheDocument()
  await user.click(toggle)
  expect(screen.getByLabelText('Selection')).toHaveTextContent('native-boolean/on')
})

test('Given unavailable named reasoning metadata, Then the composer preserves its choice and cannot modify reasoning', async () => {
  const local = { ...luna, key: 'native-pending', provider: 'ollama', status: 'unavailable', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' }, unavailable_reason: 'Preparing model automatically.' }
  mockApi({ ...openModels, 'GET /models': { items: [local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model:/ }))
  expect(screen.getByLabelText('Selection')).toHaveTextContent('native-pending/low')
  expect(screen.queryByRole('menuitem', { name: /Reasoning effort/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('menuitemcheckbox', { name: 'Reasoning' })).not.toBeInTheDocument()
  expect(screen.getByRole('menuitemradio', { name: /GPT-5.6 Luna/ })).toHaveAttribute('aria-disabled', 'true')
})

const localMissing = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'K2 Horizon 7B', status: 'unavailable', reasoning_efforts: ['default'], unavailable_reason: 'Download weights in Settings to use this model.', unavailable_code: 'MODEL_WEIGHTS_MISSING', installation: { state: 'missing', weights_present: false, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 0, total_bytes: 5592218900, job_id: null, digest: null, updated_at: null, error: null } }

test('Given an installed model preparing automatically, When server polling reports readiness, Then the composer permits its selection', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let model = { ...localMissing, unavailable_code: 'LOCAL_MODEL_REVALIDATION_REQUIRED', unavailable_reason: 'Preparing this model automatically.', installation: { ...localMissing.installation, state: 'ready', weights_present: true } }
  mockApi({ ...openModels, 'GET /models': () => json({ items: [luna, model] }), 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user, client, unmount } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  const item = screen.getByRole('menuitemradio', { name: /K2 Horizon 7B/ })
  expect(item).toHaveAttribute('aria-disabled', 'true')
  await user.click(item)
  expect(screen.getByLabelText('Selection')).toHaveTextContent('gpt-5.6-luna/low')
  model = { ...model, status: 'available', unavailable_code: '', unavailable_reason: '' }
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  await waitFor(() => expect(screen.getByRole('menuitemradio', { name: /K2 Horizon 7B/ })).toHaveAttribute('aria-disabled', 'false'))
  await user.click(screen.getByRole('menuitemradio', { name: /K2 Horizon 7B/ }))
  expect(screen.getByLabelText('Selection')).toHaveTextContent('ifm-k2-horizon-7b/default')
  unmount()
  client.clear()
})

test('Given missing local weights, When explored by keyboard, Then the explanation is discoverable and selection is guarded', async () => {
  mockApi({ ...openModels, 'GET /models': { items: [luna, localMissing] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  const item = await screen.findByRole('menuitemradio', { name: /K2 Horizon 7B/ })
  expect(item).toHaveTextContent(/Download weights/)
  await user.keyboard('{Home}{ArrowDown}')
  expect(item).toHaveFocus()
  await user.keyboard('{Enter}')
  expect(screen.getByLabelText('Selection')).toHaveTextContent('gpt-5.6-luna/low')
  expect(item).toHaveAttribute('aria-disabled', 'true')
})

test('Given deleted default weights, Then the selected model remains visible and no hosted model replaces it', async () => {
  mockApi({ ...openModels, 'GET /models': { items: [luna, localMissing] }, 'GET /settings': { default_model: localMissing.key, reasoning_effort: 'default' } })
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

test('Given the picker is open, Then it offers models and reasoning only, with no default or settings shortcuts', async () => {
  const { calls } = mockApi({ 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  await chooseEffort(user, 'High')
  await user.click(screen.getByRole('button', { name: 'Model: GPT-5.6 Luna, High reasoning' }))
  expect(await screen.findByRole('menuitemradio', { name: /GPT-5.6 Luna/ })).toBeVisible()
  expect(screen.queryByRole('menuitem', { name: /default/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('menuitem', { name: 'Model settings' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
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

test('Given a verified local thinking model, When choosing explicit levels, Then aliases stay out of its menu and named IDs are kept', async () => {
  const local = { ...localMissing, status: 'available', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high', 'research'], reasoning_aliases: { default: 'high', on: 'high' }, unavailable_reason: null, unavailable_code: null, installation: { ...localMissing.installation, state: 'ready', weights_present: true } }
  mockApi({ 'GET /models': { items: [luna, local] }, 'GET /settings': { default_model: local.key, reasoning_effort: 'default' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: 'Model: K2 Horizon 7B, High reasoning' }))
  await chooseEffort(user, 'Low')
  expect(screen.getByLabelText('Selection')).toHaveTextContent('ifm-k2-horizon-7b/low')
  await user.click(screen.getByRole('button', { name: 'Model: K2 Horizon 7B, Low reasoning' }))
  await chooseEffort(user, 'research')
  expect(screen.getByLabelText('Selection')).toHaveTextContent('ifm-k2-horizon-7b/research')
})


test('Given local and hosted models, When switching between them, Then their reasoning options remain separate', async () => {
  const hosted = { ...luna, reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'] }
  const local = { ...localMissing, status: 'available', reasoning_efforts: ['default', 'none', 'on', 'low', 'medium', 'high'], reasoning_aliases: { default: 'high', on: 'high' }, unavailable_reason: null, unavailable_code: null, installation: { ...localMissing.installation, state: 'ready', weights_present: true } }
  mockApi({ ...openModels, 'GET /models': { items: [hosted, local] }, 'GET /settings': { default_model: hosted.key, reasoning_effort: 'xhigh' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: 'Model: GPT-5.6 Luna, Extra high reasoning' }))
  await chooseEffort(user, 'Max')
  expect(screen.getByLabelText('Selection')).toHaveTextContent('gpt-5.6-luna/max')
  await user.click(screen.getByRole('button', { name: 'Model: GPT-5.6 Luna, Max reasoning' }))
  await user.click(screen.getByRole('menuitemradio', { name: /K2 Horizon 7B/ }))
  expect(screen.getByLabelText('Selection')).toHaveTextContent('ifm-k2-horizon-7b/high')
  await user.click(screen.getByRole('button', { name: 'Model: K2 Horizon 7B, High reasoning' }))
  act(() => screen.getByRole('menuitem', { name: /Reasoning effort/ }).focus())
  await user.keyboard('{ArrowRight}')
  const high = await screen.findByRole('menuitemradio', { name: 'High' })
  expect(high).toBeVisible()
  expect(within(high.closest('[role="menu"]') as HTMLElement).getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual(['None', 'Low', 'Medium', 'High'])
  expect(screen.queryByRole('menuitemradio', { name: 'Extra high' })).not.toBeInTheDocument()
  expect(screen.queryByRole('menuitemradio', { name: 'Max' })).not.toBeInTheDocument()
})

test('Given chat, search and ranking models, Then the composer lists only the chat models', async () => {
  // luna carries no kind, like responses before ARA-070: the schema default makes it a chat model.
  const search = { ...luna, kind: 'embedding', key: 'qwen3-embedding-4b', provider: 'ollama', model_id: 'qwen3-embedding:4b', display_name: 'Qwen3 Embedding 4B', status: 'available', reasoning_efforts: ['default'] }
  const ranking = { ...search, kind: 'reranker', key: 'qwen3-reranker', model_id: 'qwen3-reranker:0.6b', display_name: 'Qwen3 Reranker' }
  const terra = { ...luna, kind: 'chat', key: 'gpt-5.6-terra', model_id: 'gpt-5.6-terra', display_name: 'GPT-5.6 Terra' }
  mockApi({ 'GET /models': { items: [search, luna, ranking, terra] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount()
  await user.click(await screen.findByRole('button', { name: /^Model: GPT-5.6 Luna/ }))
  const menu = await screen.findByRole('menu')
  expect(within(menu).getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual(['GPT-5.6 Lunagpt-5.6-luna', 'GPT-5.6 Terragpt-5.6-terra'])
})
