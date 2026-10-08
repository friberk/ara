import { screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { mockApi, noContent } from '@/test/fetch-routes'
import { peekQuestion } from '@/lib/pending-questions'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', status: 'configured', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const readyPaper = { id: 'p1', title: 'Traceable research systems', authors: ['Ada Researcher'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const chat = { id: 'c1', paper_id: 'p1', document_id: 'd1', title: 'Which datasets were used?', title_source: 'auto', created_at: '2026-10-08T10:00:00Z', paper_title: readyPaper.title, last_activity_at: '2026-10-08T12:00:00Z', message_count: 2, last_question_preview: 'Which datasets were used?' }
const search = { id: 's1', provider: 'openalex', query: 'graph transformers', created_at: '2026-10-08T09:00:00Z', last_searched_at: '2026-10-08T11:00:00Z' }
afterEach(() => vi.unstubAllGlobals())

test('Given the home route, Then the workspace navigation and the research composer are offered', async () => {
  mockApi({})
  const { user } = renderApp('/')
  const nav = screen.getByRole('navigation', { name: 'Workspace' })
  for (const name of ['New research', 'Library', 'Activity']) expect(within(nav).getByRole('link', { name })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Settings' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'What are you researching?' })).toBeVisible()
  expect(screen.getByRole('textbox', { name: 'Research topic' })).toBeVisible()
  // The composer autofocuses; from a fresh document focus the skip link is the first tab stop.
  ;(document.activeElement as HTMLElement | null)?.blur()
  await user.tab()
  expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveFocus()
})

test('Given a topic in the home composer, When Enter is pressed, Then the search is recorded and results open', async () => {
  const { calls } = mockApi({ 'POST /search-history': { ...search, query: 'graph transformers' } })
  const { user } = renderApp('/')
  await user.type(screen.getByRole('textbox', { name: 'Research topic' }), 'graph transformers{Enter}')
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/search-history')).toBe(true))
  expect(calls.find((call) => call.path === '/search-history' && call.method === 'POST')?.body).toEqual({ provider: 'openalex', query: 'graph transformers' })
  await waitFor(() => expect(calls.some((call) => call.path === '/search' && call.url.searchParams.get('q') === 'graph transformers')).toBe(true))
})

test('Given an empty composer, Then Search papers stays disabled and Shift+Enter adds a line', async () => {
  mockApi({})
  const { user } = renderApp('/')
  expect(screen.getByRole('button', { name: 'Search papers' })).toBeDisabled()
  const input = screen.getByRole('textbox', { name: 'Research topic' })
  await user.type(input, 'first{Shift>}{Enter}{/Shift}second')
  expect(input).toHaveValue('first\nsecond')
})

test('Given a library paper chosen in the composer, When a question is asked, Then a chat opens with the question queued once', async () => {
  const { calls } = mockApi({
    'GET /papers': { items: [readyPaper] },
    'GET /papers/p1': readyPaper,
    'GET /models': { items: [luna] },
    'GET /settings': { default_model: luna.key, reasoning_effort: 'low' },
    'POST /papers/p1/chats': { id: 'c9', paper_id: 'p1', document_id: 'd1', title: 'Paper discussion', created_at: '2026-10-08T12:00:00Z' },
  })
  const { user } = renderApp('/')
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  await user.click(await screen.findByRole('option', { name: /Traceable research systems/ }))
  const question = screen.getByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(screen.getByRole('button', { name: /^Model: GPT-5.6 Luna/ })).toBeEnabled())
  await user.type(question, 'Which datasets were used?')
  await user.click(screen.getByRole('button', { name: 'Ask question' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/papers/p1/chats')).toBe(true))
  expect(peekQuestion('c9')).toMatchObject({ content: 'Which datasets were used?', settings: { model: luna.key, reasoning_effort: 'low' } })
  expect(peekQuestion('c9')?.request_id).toMatch(/^[0-9a-f-]{36}$/)
})

test('Given recent chats and searches, Then the sidebar lists them by activity and a chat can be renamed and deleted', async () => {
  let title = chat.title
  const { calls } = mockApi({
    'GET /chats': () => new Response(JSON.stringify({ items: [{ ...chat, title }] }), { headers: { 'Content-Type': 'application/json' } }),
    'GET /search-history': { items: [search] },
    'PATCH /chats/c1': ({ body }) => { title = (body as { title: string }).title; return new Response(JSON.stringify({ ...chat, title, title_source: 'manual' }), { headers: { 'Content-Type': 'application/json' } }) },
    'DELETE /chats/c1': () => noContent(),
  })
  const { user } = renderApp('/')
  const links = await screen.findAllByRole('link', { name: /Which datasets were used\?|graph transformers/ })
  expect(links.map((link) => link.textContent)).toEqual(['Which datasets were used?', 'graph transformers'])
  expect(links[0]).toHaveAttribute('href', '/papers/p1/chats/c1')
  expect(links[1]).toHaveAttribute('href', '/search?q=graph+transformers&provider=openalex')
  await user.click(screen.getByRole('button', { name: 'Options for Which datasets were used?' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Rename' }))
  const field = await screen.findByRole('textbox', { name: 'Conversation name' })
  await user.clear(field)
  await user.type(field, 'WMT datasets')
  await user.click(screen.getByRole('button', { name: 'Save name' }))
  expect(await screen.findByRole('link', { name: 'WMT datasets' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Options for WMT datasets' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  await user.click(await screen.findByRole('button', { name: 'Delete conversation' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'DELETE' && call.path === '/chats/c1')).toBe(true))
})

test('Given the theme menu, When Dark is chosen, Then the dark tokens apply and the choice persists', async () => {
  mockApi({})
  const { user } = renderApp('/')
  await user.click(screen.getByRole('button', { name: 'Theme: System' }))
  await user.click(await screen.findByRole('menuitemradio', { name: 'Dark' }))
  await waitFor(() => expect(document.documentElement).toHaveClass('dark'))
  expect(window.localStorage.getItem('theme')).toBe('dark')
})
