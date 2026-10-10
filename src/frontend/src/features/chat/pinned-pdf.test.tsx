// Older conversations continue as they are when their paper's PDF is removed (ARA-097): a chat keeps asking about
// the PDF it pinned, while a new conversation on a paper without a PDF says it needs one.
import { screen, waitFor } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { ask, assistantMessage, chatRow, included, mount, paper, settings, sse, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const withoutPdf: Paper = { ...paper, document_status: 'metadata_only', active_document_id: null }
const history = { items: [userMessage('u1', 'What was measured?'), assistantMessage('m1', 'Answer accuracy, at 86 percent.')] }

test('Given a chat pinned to a PDF its paper no longer has, Then it keeps taking questions about that PDF', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { papers: [included(paper, { document_id: 'd1' })], message_count: 2 })] },
    'GET /chats/c1/messages': history,
    'POST /chats/c1/messages/stream': () => sse([['message.started', { message_id: 'm2' }], ['message.delta', { text: 'Still there.' }], ['message.completed', { message_id: 'm2' }]]),
  })
  const { user } = mount('/papers/p1/chats/c1', { value: withoutPdf })
  expect(await screen.findByText('Answer accuracy, at 86 percent.')).toBeVisible()
  expect(await screen.findByText('This conversation uses an earlier PDF of this paper.')).toBeVisible()
  expect(screen.queryByText('Attach a PDF to ask questions about this paper.')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Research question, earlier PDF' })).toHaveTextContent('Earlier PDF')
  await ask(user, 'And the baseline?')
  await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.path === '/chats/c1/messages/stream')).toBe(true))
})

test('Given a paper without a PDF, Then a new conversation explains that it needs one', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [] } })
  mount('/papers/p1', { value: withoutPdf })
  expect(await screen.findByText('Attach a PDF to ask questions about this paper.')).toBeVisible()
})
