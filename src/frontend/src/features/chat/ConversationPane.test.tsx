import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { testClient } from '@/test/render'
// Runs against the real content module (ARA-035): inline chips and the source list are named "Source, page N".
import { assistantMessage, ask, chatRow, citation, luna, marker, mount, paper, settings, sse, userMessage } from './pane-test-kit'
import { paperChatsKey } from './use-paper-chats'

afterEach(() => vi.unstubAllGlobals())

test('Given a ready chat, When a question streams, Then the answer cites page 2 and its chips open the source in the reader', async () => {
  const answer = assistantMessage('m1', `The measured result is grounded.${marker}`, { citations: [citation] })
  let answered = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': () => json({ items: answered ? [userMessage('u1', 'What was measured?'), answer] : [] }),
    'POST /chats/c1/messages/stream': () => { answered = true; return sse([['message.started', { message_id: 'm1' }], ['message.delta', { text: 'The measured result is grounded.' }], ['message.completed', answer]]) },
    [`GET /documents/d1/chunks/${citation.chunk_id}`]: citation,
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  await ask(user, 'What was measured?')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  // The chip keeps the last word of its sentence in a nowrap span, so the sentence spans two elements.
  await waitFor(() => expect(reply).toHaveTextContent('The measured result is grounded.'))
  expect(screen.getByRole('article', { name: 'Your message' })).toHaveTextContent('What was measured?')
  await waitFor(() => expect(screen.getAllByRole('article', { name: 'Your message' })).toHaveLength(1))
  const sources = within(reply).getByRole('group', { name: 'Sources' })
  await user.click(within(sources).getByRole('button', { name: 'Source, page 2' }))
  // Each chip also names the text it supports, so the reader can mark just the sentences behind it.
  expect(workspace.showSource).toHaveBeenCalledWith(citation, 'The measured result is grounded.')
  const inline = within(reply).getAllByRole('button', { name: 'Source, page 2' }).find((chip) => !sources.contains(chip))
  expect(inline).toBeDefined()
  await user.click(inline!)
  expect(workspace.showSource).toHaveBeenCalledTimes(2)
  expect(workspace.showSource).toHaveBeenLastCalledWith(citation, 'The measured result is grounded.')
  const stream = calls.filter((call) => call.path === '/chats/c1/messages/stream')
  expect(stream).toHaveLength(1)
  expect(stream[0]?.body).toMatchObject({ content: 'What was measured?', model: luna.key, reasoning_effort: 'low' })
  expect((stream[0]?.body as { request_id: string }).request_id).toMatch(/^[0-9a-f-]{36}$/)
  // Sending refreshes the chat list so the auto-title and preview update in the switcher and sidebar.
  await waitFor(() => expect(calls.filter((call) => call.method === 'GET' && call.path === '/chats').length).toBeGreaterThan(1))
})

test('Given a streaming answer, When Stop generation is pressed, Then the partial answer stays once as interrupted and nothing is resent', async () => {
  let stopped = false
  let generationRequests = 0
  const partial = assistantMessage('m2', 'Partial evidence', { state: 'interrupted' })
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c2', { title: 'Stop example' })] },
    'GET /chats/c2/messages': () => json({ items: stopped ? [userMessage('u2', 'What is supported?'), partial] : [] }),
    'POST /chats/c2/messages/stream': ({ init }) => {
      generationRequests++
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('event: message.started\ndata: {"message_id":"m2"}\n\nevent: message.delta\ndata: {"text":"Partial evidence"}\n\n'))
          init?.signal?.addEventListener('abort', () => { stopped = true; controller.error(new DOMException('Aborted', 'AbortError')) })
        },
      })
      return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    },
  })
  const { user } = mount('/papers/p1/chats/c2')
  await ask(user, 'What is supported?')
  expect(await screen.findByText('Partial evidence')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Stop generation' }))
  expect(await screen.findByText('Interrupted')).toBeVisible()
  expect(await screen.findByText('Generation stopped. The partial answer was kept.')).toBeInTheDocument()
  await waitFor(() => expect(stopped).toBe(true))
  await waitFor(() => expect(screen.getAllByText('Partial evidence')).toHaveLength(1))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeInTheDocument()
  expect(generationRequests).toBe(1)
})

test('Given a stream that ends without a final event, Then the question is not sent again and the reader is told so', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c3')] },
    'POST /chats/c3/messages/stream': () => sse([['message.started', { message_id: 'm3' }], ['message.delta', { text: 'Half an answer' }]]),
  })
  const { user } = mount('/papers/p1/chats/c3')
  await ask(user, 'Which datasets?')
  expect(await screen.findByRole('alert')).toHaveTextContent('Your question was not automatically sent again.')
  expect(calls.filter((call) => call.path === '/chats/c3/messages/stream')).toHaveLength(1)
})

test('Given a paper with no chats under StrictMode, When a suggested question is chosen, Then one chat is created, the URL opens it and one answer is requested', async () => {
  let created = false
  let answered = false
  const answer = assistantMessage('m9', 'The Orion-12 dataset is used.')
  const { calls } = mockApi({
    ...settings,
    'GET /chats': () => json({ items: created ? [chatRow('c9', { title: 'What datasets are used?' })] : [] }),
    'POST /papers/p1/chats': () => { created = true; return json({ id: 'c9', paper_id: 'p1', document_id: 'd1', title: 'Paper discussion', created_at: '2026-10-08T12:00:00Z' }, 201) },
    'GET /chats/c9/messages': () => json({ items: answered ? [userMessage('u9', 'What datasets are used?'), answer] : [] }),
    'POST /chats/c9/messages/stream': () => { answered = true; return sse([['message.started', { message_id: 'm9' }], ['message.delta', { text: answer.content }], ['message.completed', answer]]) },
  })
  const { user } = mount('/papers/p1', { strict: true })
  const suggestions = await screen.findByRole('group', { name: 'Suggested questions' })
  for (const question of ['What problem does this paper address?', 'What is the main idea of the proposed approach?', 'What datasets are used?', 'What are the major limitations?', 'How does this method compare with the baselines?']) {
    expect(within(suggestions).getByRole('button', { name: question })).toBeVisible()
  }
  await waitFor(() => expect(within(suggestions).getByRole('button', { name: 'What datasets are used?' })).toBeEnabled())
  await user.click(within(suggestions).getByRole('button', { name: 'What datasets are used?' }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c9'))
  expect(await screen.findByText('The Orion-12 dataset is used.')).toBeVisible()
  await new Promise((resolve) => setTimeout(resolve, 50))
  expect(calls.filter((call) => call.method === 'POST' && call.path === '/papers/p1/chats')).toHaveLength(1)
  const stream = calls.filter((call) => call.path === '/chats/c9/messages/stream')
  expect(stream).toHaveLength(1)
  expect(stream[0]?.body).toMatchObject({ content: 'What datasets are used?', model: luna.key, reasoning_effort: 'low' })
})

test('Given a metadata-only paper, Then the composer is disabled and the footnote says how to enable questions', async () => {
  mockApi(settings)
  mount('/papers/p1', { value: { ...paper, document_status: 'metadata_only', active_document_id: null } })
  expect(await screen.findByText('Attach a PDF to ask questions about this paper.')).toBeVisible()
  expect(screen.getByRole('textbox', { name: 'Question about this paper' })).toBeDisabled()
  expect(within(screen.getByRole('group', { name: 'Suggested questions' })).getByRole('button', { name: 'What datasets are used?' })).toBeDisabled()
  expect(await within(screen.getByRole('article', { name: 'Paper summary' })).findByRole('button', { name: 'Generate summary' })).toBeDisabled()
})

test('Given several chats, When another is chosen in the switcher, Then its URL opens and an earlier PDF is marked', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { title: 'Research question', last_question_preview: 'What was measured?' }), chatRow('c2', { title: 'Older discussion', document_id: 'd0', last_activity_at: '2026-10-07T12:00:00Z' })] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: /Research question/ }))
  const older = await screen.findByRole('menuitemradio', { name: /Older discussion/ })
  expect(older).toHaveTextContent('Earlier PDF')
  expect(screen.getByRole('menuitemradio', { name: /Research question/ })).toHaveAttribute('aria-checked', 'true')
  await user.click(older)
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c2'))
  await user.click(screen.getByRole('button', { name: 'New conversation' }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent(/^\/papers\/p1$/))
})

test('Given an answer still processing after a reload, Then the composer waits and the saved answer appears when polling finishes', async () => {
  let polls = 0
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c4')] },
    'GET /chats/c4/messages': () => {
      polls++
      const reply = polls < 2 ? assistantMessage('m4', '', { state: 'processing' }) : assistantMessage('m4', 'Finished after reload.')
      return json({ items: [userMessage('u4', 'Still working?'), reply] })
    },
  })
  mount('/papers/p1/chats/c4')
  expect(await screen.findByText('Preparing a response…')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
  expect(await screen.findByText('Finished after reload.', undefined, { timeout: 4000 })).toBeVisible()
})

test('Given the history cannot load, Then an inline error offers to try again', async () => {
  let failures = 0
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c5')] },
    'GET /chats/c5/messages': () => (failures++ === 0 ? json({ code: 'UNAVAILABLE', message: 'The conversation could not load.' }, 503) : json({ items: [userMessage('u5', 'Loaded on retry')] })),
  })
  const { user } = mount('/papers/p1/chats/c5')
  expect(await screen.findByRole('alert')).toHaveTextContent('The conversation could not load.')
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText('Loaded on retry')).toBeVisible()
})

test('Given a chat created elsewhere and a stale cached chat list, Then the pane waits for the list instead of saying the chat is missing', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c7', { title: 'Asked from home' })] }, 'GET /chats/c7/messages': { items: [userMessage('u7', 'Asked from home')] } })
  const client = testClient()
  client.setQueryData(paperChatsKey('p1'), { items: [] })
  mount('/papers/p1/chats/c7', { client })
  expect(screen.queryByText('Conversation not found')).not.toBeInTheDocument()
  expect(await screen.findByRole('article', { name: 'Your message' })).toHaveTextContent('Asked from home')
})

test('Given legacy chats on the default title, Then the switcher names them like the sidebar and still lists empty ones', async () => {
  mockApi({
    ...settings,
    'GET /chats': {
      items: [
        chatRow('c1', { title: 'Paper discussion', title_source: 'default', last_question_preview: 'What is this paper about?', message_count: 2 }),
        chatRow('c2', { title: 'Paper discussion', title_source: 'default', last_question_preview: null, message_count: 0, last_activity_at: '2026-10-07T12:00:00Z' }),
      ],
    },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: 'What is this paper about?' }))
  expect(await screen.findByRole('menuitemradio', { name: /^What is this paper about\?/ })).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByRole('menuitemradio', { name: /^Paper discussion/ })).toHaveTextContent('No questions yet')
})

test('Given auto-titled chats, Then a row repeats its question only when a later question differs', async () => {
  mockApi({
    ...settings,
    'GET /chats': {
      items: [
        chatRow('c1', { title: 'What datasets are used', title_source: 'auto', last_question_preview: 'What datasets are used?', message_count: 2 }),
        chatRow('c2', { title: 'What problem does this paper address', title_source: 'auto', last_question_preview: 'What are the major limitations?', message_count: 4 }),
      ],
    },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: 'What datasets are used' }))
  const single = await screen.findByRole('menuitemradio', { name: /^What datasets are used/ })
  expect(single.textContent?.match(/What datasets are used/g)).toHaveLength(1)
  expect(screen.getByRole('menuitemradio', { name: /^What problem does this paper address/ })).toHaveTextContent('What are the major limitations?')
})

test('Given the open chat uses an earlier PDF, Then the switcher label marks it and says so in its accessible name', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { title: 'Old PDF chat', document_id: 'd0' })] } })
  mount('/papers/p1/chats/c1')
  const trigger = await screen.findByRole('button', { name: 'Old PDF chat, earlier PDF' })
  expect(within(trigger).getByText('Earlier PDF')).toBeVisible()
})
