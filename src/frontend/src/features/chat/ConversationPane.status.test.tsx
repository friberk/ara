// Retrieval progress while an answer is prepared (ARA-078): message.status names the stage before any text arrives.
import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { ask, assistantMessage, chatRow, mount, settings, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

/** A stream response the test writes one event at a time. */
function controlledStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value } })
  return {
    response: () => new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    push: (event: string, data: unknown) => controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => controller.close(),
  }
}

const announced = (text: string) => screen.queryAllByRole('status').some((node) => node.textContent === text)
// The placeholder article is replaced by the answer's own once it starts, so look it up each time.
const reply = () => screen.getByRole('article', { name: 'Assistant message' })

test('Given an answer being prepared, When status events arrive, Then the reader and the live region follow each stage and unknown stages are ignored', async () => {
  const stream = controlledStream()
  const answer = assistantMessage('m1', 'BM25 reached 71.2 recall.')
  let answered = false
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': () => json({ items: answered ? [userMessage('u1', 'What recall did BM25 reach?'), answer] : [] }),
    'POST /chats/c1/messages/stream': () => { answered = true; return stream.response() },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'What recall did BM25 reach?')
  stream.push('message.started', { message_id: 'm1' })
  stream.push('message.status', { message_id: 'm1', stage: 'daydreaming' })
  await waitFor(() => expect(within(reply()).getByText('Preparing a response…')).toBeVisible())

  for (const stage of ['planning', 'retrieving', 'reranking']) {
    stream.push('message.status', { message_id: 'm1', stage })
    await waitFor(() => expect(within(reply()).getByText('Searching the paper…')).toBeVisible())
    expect(announced('Searching the paper…')).toBe(true)
  }
  stream.push('message.status', { message_id: 'm1', stage: 'generating' })
  await waitFor(() => expect(within(reply()).getByText('Writing the answer…')).toBeVisible())
  expect(within(reply()).queryByText('Searching the paper…')).not.toBeInTheDocument()
  expect(announced('Writing the answer…')).toBe(true)

  stream.push('message.status', { message_id: 'm1', stage: 'pondering' })
  stream.push('message.delta', { text: 'BM25 reached' })
  const partial = await screen.findByText('BM25 reached')
  const status = within(reply()).getByText('Writing the answer…')
  // The stage sits above the text it describes.
  expect(status.compareDocumentPosition(partial) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

  stream.push('message.completed', answer)
  stream.close()
  expect(await screen.findByText('BM25 reached 71.2 recall.')).toBeVisible()
  expect(screen.queryByText('Writing the answer…')).not.toBeInTheDocument()
  await waitFor(() => expect(announced('Response complete.')).toBe(true))
})

test('Given a server that sends no status events, Then the answer streams as before', async () => {
  const answer = assistantMessage('m2', 'Plain answer.')
  const stream = controlledStream()
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'POST /chats/c1/messages/stream': () => stream.response() })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'Anything?')
  stream.push('message.started', { message_id: 'm2' })
  await waitFor(() => expect(within(reply()).getByText('Preparing a response…')).toBeVisible())
  expect(announced('Assistant is responding.')).toBe(true)
  stream.push('message.delta', { text: 'Plain' })
  expect(await screen.findByText('Plain')).toBeVisible()
  expect(screen.queryByText(/Searching the paper|Writing the answer/)).not.toBeInTheDocument()
  stream.push('message.completed', answer)
  stream.close()
  expect(await screen.findByText('Plain answer.')).toBeVisible()
})

test('Given background local work holds the runtime, When the waiting status arrives, Then the reader and the live region say the answer is waiting until search starts', async () => {
  const stream = controlledStream()
  const answer = assistantMessage('m3', 'BM25 reached 71.2 recall.')
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'POST /chats/c1/messages/stream': () => stream.response() })
  const { user } = mount('/papers/p1/chats/c1')
  await ask(user, 'What recall did BM25 reach?')
  stream.push('message.started', { message_id: 'm3' })
  stream.push('message.status', { message_id: 'm3', stage: 'waiting' })
  await waitFor(() => expect(within(reply()).getByText('Waiting for the local model…')).toBeVisible())
  expect(announced('Waiting for the local model…')).toBe(true)

  stream.push('message.status', { message_id: 'm3', stage: 'planning' })
  await waitFor(() => expect(within(reply()).getByText('Searching the paper…')).toBeVisible())
  expect(within(reply()).queryByText('Waiting for the local model…')).not.toBeInTheDocument()
  stream.push('message.completed', answer)
  stream.close()
  expect(await screen.findByText('BM25 reached 71.2 recall.')).toBeVisible()
})
