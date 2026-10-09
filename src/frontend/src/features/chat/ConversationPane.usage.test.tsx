// The context and cost ring inside the docked composer (ARA-085).
import { screen, waitFor } from '@testing-library/react'
import type { ChatUsage } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { assistantMessage, ask, chatRow, luna, mount, paper, settings, sse, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const zero = '0.00000000'
const cost = { total: zero, answers: zero, planning: zero, compaction: zero, embeddings: zero, reranking: zero, local: false, unrecorded_turns: 0 }
const before: ChatUsage = { context: { used_tokens: null, input_budget: 32_000, window: 32_000, model: luna.key }, cost }
const after: ChatUsage = { context: { ...before.context, used_tokens: 8_000 }, cost: { ...cost, total: '0.00420000', answers: '0.00420000' } }

test('Given an open chat, Then the ring sits in the composer toolbar for the selected model, empty with $0.00', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [] }, 'GET /chats/c1/usage': before })
  mount('/papers/p1/chats/c1')
  const ring = await screen.findByRole('button', { name: 'Context 0% used of 32k tokens. $0.00 this chat.' })
  const composer = screen.getByRole('textbox', { name: 'Question about this paper' }).closest('form')
  expect(composer).toContainElement(ring)
  const usage = calls.find((call) => call.path === '/chats/c1/usage')
  expect(usage?.url.searchParams.get('model')).toBe(luna.key)
  expect(usage?.url.searchParams.get('reasoning_effort')).toBe('low')
})

test('Given a streamed answer completes, Then the ring and cost update without a reload', async () => {
  const answer = assistantMessage('m1', 'It measured accuracy.')
  let answered = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': () => json({ items: answered ? [userMessage('u1', 'What was measured?'), answer] : [] }),
    'GET /chats/c1/usage': () => json(answered ? after : before),
    'POST /chats/c1/messages/stream': () => { answered = true; return sse([['message.started', { message_id: 'm1' }], ['message.completed', answer]]) },
  })
  const { user } = mount('/papers/p1/chats/c1')
  await screen.findByRole('button', { name: 'Context 0% used of 32k tokens. $0.00 this chat.' })
  await ask(user, 'What was measured?')
  expect(await screen.findByRole('button', { name: 'Context 25% used of 32k tokens. $0.0042 this chat.' })).toBeVisible()
  expect(calls.filter((call) => call.path === '/chats/c1/usage').length).toBeGreaterThanOrEqual(2)
})

test('Given the new-conversation start, Then there is no chat to measure: no ring and no usage request', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [] } })
  mount(`/papers/${paper.id}`)
  await screen.findByRole('textbox')
  await waitFor(() => expect(calls.some((call) => call.path === '/chats')).toBe(true))
  expect(screen.queryByRole('button', { name: /^Context/ })).not.toBeInTheDocument()
  expect(calls.some((call) => call.path.endsWith('/usage'))).toBe(false)
})
