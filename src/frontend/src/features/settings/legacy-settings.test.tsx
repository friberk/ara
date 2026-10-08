// Legacy behaviour tests moved from pages/workflows.test.tsx (ARA-033). The feature owner replaces them
// with tests for the redesigned UI while keeping the same behavioural coverage.
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'

function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function mount(path: string) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>); return client }
afterEach(() => vi.unstubAllGlobals())


test('Given unavailable and supported models, Then exact IDs and reasoning capabilities govern selection', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/settings') ? response({ default_model: 'gpt-5.6-luna', reasoning_effort: 'low' }) : response({ items: [{ key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }, { key: 'unavailable-exact', provider: 'openai', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [], supports_streaming: false, supports_structured_output: false, context_window: 32000 }] })))
  mount('/settings')
  const model = await screen.findByRole('combobox', { name: 'Model' })
  await waitFor(() => expect(model).toHaveValue('gpt-5.6-luna'))
  expect(screen.getByRole('option', { name: /Unavailable model/ })).toBeDisabled()
  expect(screen.getByRole('combobox', { name: 'Reasoning effort' })).toHaveValue('low')
  expect(screen.getByRole('option', { name: 'high' })).toBeVisible()
})

