// Test-after coverage (ARA-036 TDD audit): behaviour that shipped before any test covered it. Each test was
// confirmed by breaking the behaviour it covers, watching the test fail, and restoring the code.
import { isEditable, textIn } from '@/test/editor'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { testClient } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'
import { queryKeys } from '@/lib/query-keys'
import { queueQuestion } from '@/lib/pending-questions'
import { ask, assistantMessage, chatRow, included, mount, paper, settings, userMessage } from './pane-test-kit'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

/** A stream the test feeds frame by frame. */
function controlledStream() {
  let enqueue: (text: string) => void = () => {}
  let close = () => {}
  const handler = ({ init }: { init?: RequestInit }) => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        enqueue = (text) => controller.enqueue(new TextEncoder().encode(text))
        close = () => controller.close()
        init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')))
      },
    })
    return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
  }
  return { handler, push: (event: string, data: unknown) => enqueue(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`), close: () => close() }
}
const never = () => new Promise<Response>(() => {})

test('Given a question sent with Enter, Then one answer is requested and the composer clears', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'POST /chats/c1/messages/stream': controlledStream().handler })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, 'Sent with Enter{Enter}')
  await waitFor(() => expect(calls.filter((call) => call.path === '/chats/c1/messages/stream')).toHaveLength(1))
  expect(textIn(input)).toBe('')
})

test('Given an answer starting, Then it reads "Preparing a response…" and screen readers hear it start and finish', async () => {
  const stream = controlledStream()
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'POST /chats/c1/messages/stream': stream.handler })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'Anything?')
  const pending = await screen.findByRole('article', { name: 'Assistant message' })
  expect(pending).toHaveTextContent('Preparing a response…')
  expect(screen.getByText('Assistant is responding.')).toBeInTheDocument()
  stream.push('message.started', { message_id: 'm1' })
  stream.push('message.completed', assistantMessage('m1', 'Done now.'))
  stream.close()
  expect(await screen.findByText('Response complete.')).toBeInTheDocument()
})

test('Given the history refetches mid-stream, Then the question shows once and the live draft replaces its saved partial', async () => {
  const stream = controlledStream()
  let saved: unknown[] = []
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': () => json({ items: saved }), 'POST /chats/c1/messages/stream': stream.handler })
  const client = testClient()
  const { user } = mount('/papers/p1/chats/c1', { client })
  await ask(user, 'Mid-stream question?')
  stream.push('message.started', { message_id: 'm1' })
  stream.push('message.delta', { text: 'Live draft text' })
  await screen.findByText('Live draft text')
  saved = [userMessage('u1', 'Mid-stream question?'), assistantMessage('m1', 'Live', { state: 'processing' })]
  await client.refetchQueries({ queryKey: queryKeys.messages('c1') })
  expect(client.getQueryData(queryKeys.messages('c1'))).toEqual({ items: saved })
  // The query notifies React on a later tick; let that render land before reading the thread.
  await new Promise((resolve) => setTimeout(resolve, 50))
  expect(screen.getAllByRole('article', { name: 'Your message' })).toHaveLength(1)
  expect(screen.getByText('Live draft text')).toBeInTheDocument()
  expect(screen.queryByText('Live')).not.toBeInTheDocument()
})

test('Given streaming text, Then the thread follows it near the bottom and holds still once the reader scrolls up', async () => {
  const stream = controlledStream()
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'POST /chats/c1/messages/stream': stream.handler })
  const { user } = mount('/papers/p1/chats/c1')
  const thread = await screen.findByRole('region', { name: 'Conversation' })
  let top = 0
  Object.defineProperty(thread, 'scrollHeight', { configurable: true, value: 2000 })
  Object.defineProperty(thread, 'clientHeight', { configurable: true, value: 500 })
  Object.defineProperty(thread, 'scrollTop', { configurable: true, get: () => top, set: (value: number) => { top = value } })
  await ask(user, 'Follow me?')
  stream.push('message.started', { message_id: 'm1' })
  top = 1450
  fireEvent.scroll(thread)
  stream.push('message.delta', { text: 'First words' })
  await screen.findByText('First words')
  expect(top).toBe(2000)
  top = 0
  fireEvent.scroll(thread)
  stream.push('message.delta', { text: ' and more' })
  await screen.findByText('First words and more')
  expect(top).toBe(0)
})

test('Given a copy that the browser refuses, Then the copy button says so', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [assistantMessage('m1', 'Some answer.')] } })
  const { user } = mount('/papers/p1/chats/c1')
  const copy = await screen.findByRole('button', { name: 'Copy answer' })
  vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Denied'))
  await user.click(copy)
  expect(await screen.findByRole('button', { name: 'Could not copy. Select the text instead.' })).toBeVisible()
})

test('Given an interrupted answer with no text, Then it says no answer was saved', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [userMessage('u1', 'Lost?'), assistantMessage('m1', '', { state: 'interrupted' })] } })
  mount('/papers/p1/chats/c1')
  expect(within(await screen.findByRole('article', { name: 'Assistant message' })).getByText('No answer was saved.')).toBeVisible()
})

test('Given the history still loading, Then a loading placeholder stands in for the thread', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': never })
  mount('/papers/p1/chats/c1')
  // The thread is open (its summary card shows) before the history placeholder is looked for.
  await screen.findByRole('article', { name: 'Paper summary' })
  expect(screen.getByRole('status', { name: 'Loading conversation' })).toBeInTheDocument()
})

test('Given a chat URL while the chat list is still loading, Then the pane waits instead of reporting the chat missing', async () => {
  mockApi({ ...settings, 'GET /chats': never })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByRole('status', { name: 'Loading conversation' })).toBeInTheDocument()
  expect(screen.queryByText('Conversation not found')).not.toBeInTheDocument()
})

test('Given the chat list fails, Then the pane shows the error inline and Try again loads the chat', async () => {
  let failures = 0
  mockApi({
    ...settings,
    'GET /chats': () => (failures++ === 0 ? json({ code: 'UNAVAILABLE', message: 'Conversations could not load.' }, 503) : json({ items: [chatRow('c1')] })),
    'GET /chats/c1/messages': { items: [userMessage('u1', 'Back again')] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  expect(await screen.findByRole('alert')).toHaveTextContent('Conversations could not load.')
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText('Back again')).toBeVisible()
})

test('Given a chat URL that is not in the list, Then the pane says so and offers a new conversation', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] } })
  const { user } = mount('/papers/p1/chats/deleted-chat')
  expect(await screen.findByRole('heading', { name: 'Conversation not found' })).toBeVisible()
  const buttons = screen.getAllByRole('button', { name: 'New conversation' })
  await user.click(buttons[buttons.length - 1]!)
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent(/^\/papers\/p1$/))
})

test('Given a paper whose PDF failed, Then the composer explains how to enable questions', async () => {
  mockApi(settings)
  mount('/papers/p1', { value: { ...paper, document_status: 'failed' } })
  expect(await screen.findByText('PDF processing failed. Attach a text-based PDF to ask questions.')).toBeVisible()
  expect(isEditable(screen.getByRole('textbox', { name: 'Question about this paper' }))).toBe(false)
})

test('Given the server refuses a new chat, Then the reason is shown inline', async () => {
  mockApi({ ...settings, 'POST /chats': () => json({ code: 'PAPER_NOT_READY', message: '“Evidence based research” needs a processed PDF before you can ask about it.' }, 409) })
  const { user } = mount('/papers/p1')
  await ask(user, 'Can I start?')
  expect(await screen.findByRole('alert')).toHaveTextContent('“Evidence based research” needs a processed PDF before you can ask about it.')
})

test('Given a new chat, Then its thread opens and asks at once, without waiting for the chat list to refetch', async () => {
  let listCalls = 0
  const { calls } = mockApi({
    ...settings,
    'GET /chats': () => (listCalls++ === 0 ? json({ items: [] }) : never()),
    'POST /chats': () => json({ id: 'c9', paper_id: 'p1', papers: [included(paper)], title: 'Paper discussion', title_source: 'default', created_at: '2026-10-08T12:00:00Z' }, 201),
    'POST /chats/c9/messages/stream': controlledStream().handler,
  })
  const { user } = mount('/papers/p1')
  await ask(user, 'Straight away?')
  await waitFor(() => expect(calls.filter((call) => call.path === '/chats/c9/messages/stream')).toHaveLength(1))
  expect(screen.getByRole('article', { name: 'Your message' })).toHaveTextContent('Straight away?')
})

test('Given the reader scrolled up, When a question is sent, Then the thread returns to the newest content', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [userMessage('u0', 'Earlier question')] }, 'POST /chats/c1/messages/stream': controlledStream().handler })
  const { user } = mount('/papers/p1/chats/c1')
  await screen.findByText('Earlier question')
  const thread = screen.getByRole('region', { name: 'Conversation' })
  let top = 0
  Object.defineProperty(thread, 'scrollHeight', { configurable: true, value: 2000 })
  Object.defineProperty(thread, 'clientHeight', { configurable: true, value: 500 })
  Object.defineProperty(thread, 'scrollTop', { configurable: true, get: () => top, set: (value: number) => { top = value } })
  fireEvent.scroll(thread)
  expect(await screen.findByRole('button', { name: 'Scroll to latest message' })).toBeVisible()
  await ask(user, 'Back to the bottom?')
  expect(top).toBe(2000)
  expect(screen.queryByRole('button', { name: 'Scroll to latest message' })).not.toBeInTheDocument()
})

test('Given models still loading, Then a typed question cannot be sent yet', async () => {
  mockApi({ 'GET /models': never, 'GET /settings': never })
  const { user } = mount('/papers/p1')
  await user.type(await screen.findByRole('textbox', { name: 'Question about this paper' }), 'Too early?')
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
})

test('Given an answer still processing after a reload, Then there is no Stop button and the footnote explains the wait', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [userMessage('u1', 'Still going?'), assistantMessage('m1', '', { state: 'processing' })] } })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByText('An answer is still being written. It appears here when it finishes.')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Stop generation' })).not.toBeInTheDocument()
})

test('Given a queued question while an answer is still processing, Then it waits in the composer instead of being sent', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [userMessage('u1', 'First'), assistantMessage('m1', '', { state: 'processing' })] } })
  queueQuestion('c1', { content: 'Queued behind an answer', settings: { model: 'gpt-5.6-luna', reasoning_effort: 'low' } })
  mount('/papers/p1/chats/c1')
  await waitFor(() => expect(textIn(screen.getByRole('textbox', { name: 'Question about this paper' }))).toBe('Queued behind an answer'))
  expect(calls.some((call) => call.path.endsWith('/messages/stream'))).toBe(false)
})
