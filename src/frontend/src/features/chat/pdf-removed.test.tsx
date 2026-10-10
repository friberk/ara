// A chat whose pinned PDF was removed (ARA-097): it still reads, says why it takes no new questions, and never
// claims to use an earlier PDF.
import { screen, within } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, included, mount, paper, paper2, settings, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const withoutPdf: Paper = { ...paper, document_status: 'metadata_only', active_document_id: null }
const history = { items: [userMessage('u1', 'What was measured?'), assistantMessage('m1', 'Answer accuracy, at 86 percent.')] }

test('Given a chat whose PDF was removed, Then its answers still read and the composer explains why it is locked', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { papers: [included(paper, { document_id: 'd1', pdf_removed: true })], message_count: 2 })] }, 'GET /chats/c1/messages': history })
  mount('/papers/p1/chats/c1', { value: withoutPdf })
  expect(await screen.findByText('Answer accuracy, at 86 percent.')).toBeVisible()
  expect(await screen.findByText('The PDF this conversation used was removed. Start a new conversation to ask more.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Research question, PDF removed' })).toHaveTextContent('PDF removed')
  expect(screen.queryByText('Earlier PDF')).not.toBeInTheDocument()
})

test('Given a new PDF uploaded after the removal, Then the old chat still takes no new questions', async () => {
  const replaced: Paper = { ...paper, active_document_id: 'd9' }
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { papers: [included(paper, { document_id: 'd1', pdf_removed: true })], message_count: 2 })] }, 'GET /chats/c1/messages': history })
  mount('/papers/p1/chats/c1', { value: replaced })
  expect(await screen.findByText('The PDF this conversation used was removed. Start a new conversation to ask more.')).toBeVisible()
  expect(screen.queryByText('This conversation uses an earlier PDF of this paper.')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
})

test('Given a chat over several papers where one PDF was removed, Then it says to remove that paper to ask more', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { papers: [included(paper), included(paper2, { pdf_removed: true })], message_count: 2 })] }, 'GET /chats/c1/messages': history })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByText('A PDF this conversation used was removed. Remove that paper from the conversation to ask more.')).toBeVisible()
  const chips = screen.getByRole('list', { name: 'Papers in this conversation' })
  expect(within(chips).getByRole('button', { name: `Remove ${paper2.title} from this conversation` })).toBeEnabled()
})
