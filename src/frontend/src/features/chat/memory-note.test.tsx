// Conversation memory (ARA-078): once earlier messages are summarized, the composer footnote says so and shows the summary.
import { screen, waitFor, within } from '@testing-library/react'
import type { ChatMemory } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { ask, assistantMessage, chatRow, luna, mount, settings, sse, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const defaultNote = 'Answers come from this paper’s PDF and cite their pages. Check important claims against the source.'
const memory: ChatMemory = {
  version: 2,
  summary: '## User goals\n\n- The project uses **Natural Questions** [source:12345678-1234-1234-1234-123456789abc].\n\n## Questions asked\n\n1. What recall did BM25 reach?',
  summarized_messages: 18,
  model: luna.key,
  created_at: '2026-10-09T12:00:00Z',
}
const history = { items: [userMessage('u1', 'What recall did BM25 reach?'), assistantMessage('m1', 'BM25 reached 71.2 recall.')] }

test('Given a summarized conversation, When View summary is pressed, Then the footnote names the model and the summary reads as Markdown without chips', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': history, 'GET /chats/c1/memory': { memory, total_messages: 24 } })
  const { user } = mount('/papers/p1/chats/c1')
  expect(await screen.findByText('Earlier messages are summarized to fit Luna.')).toBeVisible()
  expect(screen.queryByText(defaultNote)).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'View summary' }))
  const summary = await screen.findByRole('dialog', { name: 'Conversation summary' })
  expect(within(summary).getByRole('heading', { name: 'User goals' })).toBeVisible()
  expect(within(summary).getByText('Natural Questions').tagName).toBe('STRONG')
  expect(within(summary).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['The project uses Natural Questions.', 'What recall did BM25 reach?'])
  expect(within(summary).queryByRole('button', { name: /^Source/ })).not.toBeInTheDocument()
  expect(summary).not.toHaveTextContent('[source:')
  expect(calls.some((call) => call.method === 'GET' && call.path === '/chats/c1/memory')).toBe(true)
})

test('Given no summary yet, Then the usual footnote shows and there is nothing to view', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': history, 'GET /chats/c1/memory': { memory: null, total_messages: 2 } })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByText(defaultNote)).toBeVisible()
  await screen.findByText('BM25 reached 71.2 recall.')
  expect(screen.queryByRole('button', { name: 'View summary' })).not.toBeInTheDocument()
})

test('Given a server that cannot report memory yet, Then the usual footnote shows', async () => {
  const { calls } = mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': history, 'GET /chats/c1/memory': () => json({ code: 'NOT_IMPLEMENTED', message: 'Not implemented.' }, 501) })
  mount('/papers/p1/chats/c1')
  await waitFor(() => expect(calls.some((call) => call.path === '/chats/c1/memory')).toBe(true))
  expect(await screen.findByText(defaultNote)).toBeVisible()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('Given a summary made by a model the server no longer lists, Then the footnote does not show its raw id', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': history, 'GET /chats/c1/memory': { memory: { ...memory, model: 'retired-model:7b' }, total_messages: 24 } })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByText('Earlier messages are summarized to fit the model’s context.')).toBeVisible()
  expect(screen.queryByText(/retired-model/)).not.toBeInTheDocument()
})

test('Given a question completes, Then memory is fetched again and a new summary appears in the footnote', async () => {
  let answered = false
  const answer = assistantMessage('m2', 'Summarized answer.')
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': () => json(answered ? { items: [...history.items, userMessage('u2', 'And DPR?'), answer] } : history),
    'GET /chats/c1/memory': () => json({ memory: answered ? memory : null, total_messages: answered ? 4 : 2 }),
    'POST /chats/c1/messages/stream': () => { answered = true; return sse([['message.started', { message_id: 'm2' }], ['message.completed', answer]]) },
  })
  const { user } = mount('/papers/p1/chats/c1')
  expect(await screen.findByText(defaultNote)).toBeVisible()
  await ask(user, 'And DPR?')
  expect(await screen.findByText('Earlier messages are summarized to fit Luna.')).toBeVisible()
  expect(calls.filter((call) => call.method === 'GET' && call.path === '/chats/c1/memory').length).toBeGreaterThan(1)
})
