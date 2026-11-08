// Older conversations continue as they are when their paper's PDF is removed (ARA-097): a chat keeps asking about
// the PDF it pinned, while a new conversation on a paper without a PDF says it needs one.
import { screen, waitFor } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { ask, assistantMessage, chatRow, included, mount, paper, settings, sse, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const withoutPdf: Paper = { ...paper, document_status: 'metadata_only', active_document_id: null }
const history = { items: [userMessage('u1', 'What was measured?'), assistantMessage('m1', 'Answer accuracy, at 86 percent.')] }

const replaced: Paper = { ...paper, active_document_id: 'd2' }

test.each([
  ['no longer has', withoutPdf],
  ['has since replaced', replaced],
])('Given a chat pinned to a PDF its paper %s, When a follow-up is asked, Then the answer completes', async (_change, value) => {
  // The streamed text differs from the final answer, so seeing the final one proves the completion event was accepted.
  const answer = assistantMessage('m2', 'The baseline reached 71 percent.')
  let answered = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { papers: [included(paper, { document_id: 'd1' })], message_count: 2 })] },
    'GET /chats/c1/messages': () => json({ items: answered ? [...history.items, userMessage('u2', 'And the baseline?'), answer] : history.items }),
    'POST /chats/c1/messages/stream': () => { answered = true; return sse([['message.started', { message_id: 'm2' }], ['message.delta', { text: 'Still there.' }], ['message.completed', answer]]) },
  })
  const { user } = mount('/papers/p1/chats/c1', { value })
  expect(await screen.findByText('Answer accuracy, at 86 percent.')).toBeVisible()
  expect(await screen.findByText('This conversation uses an earlier PDF of this paper.')).toBeVisible()
  expect(screen.queryByText('Attach a PDF to ask questions about this paper.')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Research question, earlier PDF' })).toHaveTextContent('Earlier PDF')
  await ask(user, 'And the baseline?')
  expect(await screen.findByText('The baseline reached 71 percent.')).toBeVisible()
  await waitFor(() => expect(screen.queryByText('Still there.')).not.toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText(/invalid stream data/i)).not.toBeInTheDocument()
  expect(calls.find((call) => call.method === 'POST' && call.path === '/chats/c1/messages/stream')?.body).toMatchObject({ content: 'And the baseline?' })
})

test('Given a paper without a PDF, Then a new conversation explains that it needs one', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [] } })
  mount('/papers/p1', { value: withoutPdf })
  expect(await screen.findByText('Attach a PDF to ask questions about this paper.')).toBeVisible()
})
