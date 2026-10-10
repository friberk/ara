// Characterization tests written AFTER the implementation (ARA-036), for behaviour that shipped without a test
// of its own. Each one was checked by temporarily breaking the behaviour it covers and watching it fail.
import { textIn } from '@/test/editor'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { queueQuestion } from '@/lib/pending-questions'
import { json, mockApi, noContent } from '@/test/fetch-routes'
import { ask, assistantMessage, chatRow, citation, included, luna, marker, mount, paper, settings, sse, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

function hangingStream(onAbort: () => void) {
  return ({ init }: { init?: RequestInit }) => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: message.started\ndata: {"message_id":"m1"}\n\nevent: message.delta\ndata: {"text":"Still writing"}\n\n'))
        init?.signal?.addEventListener('abort', () => { onAbort(); controller.error(new DOMException('Aborted', 'AbortError')) })
      },
    })
    return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
  }
}

test('Given the provider fails mid-answer, Then its reason is shown inline and the answer is marked failed', async () => {
  let failed = false
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': () => json({ items: failed ? [userMessage('u1', 'What failed?'), assistantMessage('m1', 'Partial', { state: 'failed' })] : [] }),
    'POST /chats/c1/messages/stream': () => { failed = true; return sse([['message.started', { message_id: 'm1' }], ['message.delta', { text: 'Partial' }], ['message.failed', { code: 'PROVIDER_ERROR', message: 'The model provider is unavailable. Try again later.', message_id: 'm1' }]]) },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'What failed?')
  expect(await screen.findByRole('alert')).toHaveTextContent('The model provider is unavailable. Try again later.')
  expect(within(await screen.findByRole('article', { name: 'Assistant message' })).getByText('Failed')).toBeVisible()
})

test('Given an answer citing another document, Then it is rejected with an inline error', async () => {
  const foreign = { ...citation, document_id: 'another-document' }
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'POST /chats/c1/messages/stream': () => sse([['message.started', { message_id: 'm1' }], ['message.completed', assistantMessage('m1', `Claim.${marker}`, { citations: [foreign] })]]),
  })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'Which source?')
  await waitFor(async () => expect((await screen.findAllByRole('alert')).some((alert) => alert.textContent?.includes('The response included a source outside this document.'))).toBe(true))
})

test('Given a saved answer, When Copy answer is pressed, Then the clipboard gets page references instead of source markers', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': { items: [assistantMessage('m1', `Grounded claim.${marker}`, { citations: [citation] })] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: 'Copy answer' }))
  expect(await navigator.clipboard.readText()).toBe('Grounded claim. (p. 2)')
  expect(screen.getByRole('button', { name: 'Copied' })).toBeVisible()
})

test('Given a cited passage spanning two pages, When Copy answer is pressed, Then the clipboard names the page range (ARA-075)', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': { items: [assistantMessage('m1', `Spanning claim.${marker}`, { citations: [{ ...citation, page: 5, page_end: 6 }] })] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: 'Copy answer' }))
  expect(await navigator.clipboard.readText()).toBe('Spanning claim. (p. 5–6)')
})

test('Given a selected model that cannot stream, Then the footnote says so and Ask question stays disabled', async () => {
  mockApi({ 'GET /models': { items: [{ ...luna, supports_streaming: false }] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } })
  const { user } = mount('/papers/p1')
  expect(await screen.findByText('The selected model can’t answer questions. Choose another model.')).toBeVisible()
  await user.type(screen.getByRole('textbox', { name: 'Question about this paper' }), 'Anything?')
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
})

test('Given the open chat, When it is renamed and then deleted from the switcher, Then the API is called and the start opens', async () => {
  let title = 'Research question'
  let deleted = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': () => json({ items: deleted ? [] : [chatRow('c1', { title, message_count: 2, last_question_preview: 'Research question?' })] }),
    'PATCH /chats/c1': ({ body }) => { title = (body as { title: string }).title; return json({ ...chatRow('c1'), title, title_source: 'manual' }) },
    'DELETE /chats/c1': () => { deleted = true; return noContent() },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: 'Research question' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Rename' }))
  const field = await screen.findByRole('textbox', { name: 'Conversation name' })
  await user.clear(field)
  await user.type(field, 'Measured results')
  await user.click(screen.getByRole('button', { name: 'Save name' }))
  await user.click(await screen.findByRole('button', { name: 'Measured results' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  await user.click(await screen.findByRole('button', { name: 'Delete conversation' }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent(/^\/papers\/p1$/))
  expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ title: 'Measured results' })
  expect(calls.some((call) => call.method === 'DELETE' && call.path === '/chats/c1')).toBe(true)
})

test('Given an answer streaming, When another chat is opened, Then that stream is aborted and nothing is resent', async () => {
  let aborted = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { title: 'First chat' }), chatRow('c2', { title: 'Second chat' })] },
    'POST /chats/c1/messages/stream': hangingStream(() => { aborted = true }),
  })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'Long question?')
  expect(await screen.findByText('Still writing')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'First chat' }))
  await user.click(await screen.findByRole('menuitemradio', { name: /^Second chat/ }))
  await waitFor(() => expect(aborted).toBe(true))
  expect(calls.filter((call) => call.path.endsWith('/messages/stream'))).toHaveLength(1)
})

test('Given a queued question for a paper whose PDF is processing, Then it waits in the composer instead of being sent', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] } })
  queueQuestion('c1', { content: 'Queued while processing', settings: { model: luna.key, reasoning_effort: 'low' } })
  mount('/papers/p1/chats/c1', { value: { ...paper, document_status: 'processing' } })
  await waitFor(() => expect(textIn(screen.getByRole('textbox', { name: 'Question about this paper' }))).toBe('Queued while processing'))
  // The same words as while retrieval brings the PDF: it is on its way (ARA-086).
  expect(screen.getByText('You can ask questions once the PDF is ready.')).toBeVisible()
  expect(calls.some((call) => call.path.endsWith('/messages/stream'))).toBe(false)
})

test('Given a chat on an earlier PDF, Then the footnote says which PDF its answers use', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { papers: [included(paper, { document_id: 'd0' })] })] } })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByText('This conversation uses an earlier PDF of this paper.')).toBeVisible()
})

test('Given the reader scrolls up, Then Scroll to latest message appears, returns to the newest content and hides near the bottom', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [userMessage('u1', 'Earlier question')] } })
  const { user } = mount('/papers/p1/chats/c1')
  await screen.findByText('Earlier question')
  const thread = screen.getByRole('region', { name: 'Conversation' })
  let top = 0
  Object.defineProperty(thread, 'scrollHeight', { configurable: true, value: 2000 })
  Object.defineProperty(thread, 'clientHeight', { configurable: true, value: 500 })
  Object.defineProperty(thread, 'scrollTop', { configurable: true, get: () => top, set: (value: number) => { top = value } })
  const scrollTo = vi.fn()
  thread.scrollTo = scrollTo
  fireEvent.scroll(thread)
  await user.click(await screen.findByRole('button', { name: 'Scroll to latest message' }))
  expect(scrollTo).toHaveBeenCalledWith({ top: 2000, behavior: 'smooth' })
  top = 1450
  fireEvent.scroll(thread)
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Scroll to latest message' })).not.toBeInTheDocument())
})
