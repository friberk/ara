// Settings is a dialog over the current page, grouped by category, as in ChatGPT and Claude (ARA-109).
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import type { Model } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { renderApp, testClient } from '@/test/render'

const luna: Model = { kind: 'chat', key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 1_050_000, description: 'Built for cost-sensitive, high-volume work.', input_price_per_million: 0.2, output_price_per_million: 1.2 }
const local: Model = { ...luna, key: 'ifm-k2-horizon-7b', provider: 'ollama', model_id: 'hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M', display_name: 'IFM K2 Horizon 7B', status: 'unavailable', reasoning_efforts: ['default'], context_window: 8192, description: null, input_price_per_million: null, output_price_per_million: null, unavailable_reason: 'Download weights in Settings to use this model.', installation: { state: 'missing', weights_present: false, quantization: 'Q4_K_M', download_bytes: 5592218900, completed_bytes: 0, total_bytes: 5592218900, job_id: null, digest: null, updated_at: null, error: null } }
const base = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' }, 'GET /features': { open_models: false } }
const categories = ['General', 'Models', 'Library and search']
afterEach(() => vi.unstubAllGlobals())

/** The whole app in a data router, so a test can read the URL and press the browser's Back button. */
function renderWithHistory(path: string) {
  const client = testClient()
  const user = userEvent.setup()
  const router = createMemoryRouter([{ path: '*', element: <App /> }], { initialEntries: [path] })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { router, user, back: () => act(async () => { await router.navigate(-1) }) }
}

function mobileScreen() {
  const original = window.matchMedia
  window.matchMedia = ((query: string) => ({ matches: query.includes('max-width'), media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia
  return () => { window.matchMedia = original }
}

test('Given the sidebar Settings item, When it is used, Then a Settings dialog opens over the current page on General', async () => {
  mockApi(base)
  const { router, user } = renderWithHistory('/library')
  await user.click(screen.getByRole('button', { name: 'Settings' }))
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  const tabs = within(dialog).getByRole('tablist', { name: 'Settings categories' })
  expect(within(tabs).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(categories)
  expect(within(tabs).getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
  expect(within(dialog).getByRole('heading', { name: 'General' })).toBeVisible()
  expect(router.state.location.pathname).toBe('/library')
  expect(new URLSearchParams(router.state.location.search).has('settings')).toBe(true)
})

test('Given the dialog was opened from the sidebar, When Escape is pressed, Then it closes, the URL drops it and focus returns to Settings', async () => {
  mockApi(base)
  const { router, user } = renderWithHistory('/library')
  const opener = screen.getByRole('button', { name: 'Settings' })
  await user.click(opener)
  await screen.findByRole('dialog', { name: 'Settings' })
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Settings' })).not.toBeInTheDocument())
  expect(router.state.location.pathname).toBe('/library')
  expect(router.state.location.search).toBe('')
  await waitFor(() => expect(opener).toHaveFocus())
})

test('Given the dialog is open, When its close button is pressed, Then it closes and focus returns to Settings', async () => {
  mockApi(base)
  const { user } = renderWithHistory('/')
  const opener = screen.getByRole('button', { name: 'Settings' })
  await user.click(opener)
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  await user.click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Settings' })).not.toBeInTheDocument())
  await waitFor(() => expect(opener).toHaveFocus())
})

test('Given a category is chosen, Then the URL names it, and the browser Back button closes the dialog', async () => {
  mockApi(base)
  const { router, user, back } = renderWithHistory('/library')
  await user.click(screen.getByRole('button', { name: 'Settings' }))
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  await user.click(within(dialog).getByRole('tab', { name: 'Models' }))
  expect(within(dialog).getByRole('heading', { name: 'Models' })).toBeVisible()
  expect(new URLSearchParams(router.state.location.search).get('settings')).toBe('models')
  await back()
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Settings' })).not.toBeInTheDocument())
  expect(router.state.location.pathname).toBe('/library')
  expect(router.state.location.search).toBe('')
})

test('Given a link to a category, Then the dialog opens on it over the page, and closing keeps the page', async () => {
  mockApi(base)
  const { router, user } = renderWithHistory('/library?settings=models')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  expect(within(dialog).getByRole('tab', { name: 'Models' })).toHaveAttribute('aria-selected', 'true')
  expect(within(dialog).getByRole('heading', { name: 'Models' })).toBeVisible()
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Settings' })).not.toBeInTheDocument())
  expect(router.state.location.pathname).toBe('/library')
  expect(router.state.location.search).toBe('')
})

test('Given an old /settings link, Then home opens with the Settings dialog', async () => {
  mockApi(base)
  const { router } = renderWithHistory('/settings')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
  expect(router.state.location.pathname).toBe('/')
  expect(screen.getByRole('heading', { name: 'What are you researching?', hidden: true })).toBeInTheDocument()
})

test('Given an old /settings#local-models link with open models on, Then the dialog opens on Open models', async () => {
  mockApi({ ...base, 'GET /features': { open_models: true }, 'GET /models': { items: [luna, local] } })
  renderApp('/settings#local-models')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  await waitFor(() => expect(within(dialog).getByRole('tab', { name: 'Open models' })).toHaveAttribute('aria-selected', 'true'))
  expect(await within(dialog).findByRole('heading', { name: 'Local models' })).toBeVisible()
})

test('Given open models are off, Then there is no Open models category, and its old link falls back to General', async () => {
  mockApi(base)
  renderApp('/settings#local-models')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  expect(within(dialog).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(categories)
  expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
})

test('Given the command palette, When Model settings is chosen, Then the dialog opens on Models', async () => {
  mockApi(base)
  const { user } = renderApp('/')
  await user.keyboard('{Control>}k{/Control}')
  await user.click(await screen.findByRole('option', { name: 'Model settings' }))
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  expect(within(dialog).getByRole('tab', { name: 'Models' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.queryByPlaceholderText('Search papers, conversations and actions')).not.toBeInTheDocument()
})

test('Given the command palette, When Settings is chosen, Then the dialog opens on General', async () => {
  mockApi(base)
  const { user } = renderApp('/')
  await user.keyboard('{Control>}k{/Control}')
  await user.click(await screen.findByRole('option', { name: 'Settings' }))
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
})

test('Given a phone, When Settings opens, Then the category list shows first and drills into a panel with a way back', async () => {
  const restore = mobileScreen()
  try {
    mockApi(base)
    const { user } = renderApp('/')
    await user.click(screen.getByRole('button', { name: 'Toggle Sidebar' }))
    await user.click(await screen.findByRole('button', { name: 'Settings' }))
    const dialog = await screen.findByRole('dialog', { name: 'Settings' })
    expect(within(dialog).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(categories)
    expect(within(dialog).queryByRole('tabpanel')).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('tab', { name: 'Models' }))
    expect(within(dialog).getByRole('heading', { name: 'Models' })).toBeVisible()
    expect(within(dialog).queryByRole('tablist')).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'All settings' }))
    expect(within(dialog).getByRole('tablist', { name: 'Settings categories' })).toBeVisible()
    expect(within(dialog).queryByRole('heading', { name: 'Models' })).not.toBeInTheDocument()
  } finally {
    restore()
  }
})

// The frozen open-models panel (ARA-090) keeps its own copy, so this covers the categories everyone sees.
test('Given every category, Then no middle dot separates anything in the dialog', async () => {
  mockApi(base)
  const { user } = renderApp('/?settings=general')
  const dialog = await screen.findByRole('dialog', { name: 'Settings' })
  await waitFor(() => expect(within(dialog).getAllByRole('tab')).toHaveLength(3))
  for (const tab of within(dialog).getAllByRole('tab')) {
    await user.click(tab)
    await within(dialog).findByRole('heading', { name: tab.textContent ?? '' })
    expect(dialog.textContent).not.toContain('·')
  }
})
