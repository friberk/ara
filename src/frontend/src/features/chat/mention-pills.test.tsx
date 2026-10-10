// Sent questions keep their paper pills (ARA-096): history renders them, and a paper a question brought into the chat
// may be cited by its answer.
import { screen, waitFor, within } from '@testing-library/react'
import type { Citation, Paper } from '@/api/types'
import { isEditable } from '@/test/editor'
import { json, mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, included, mount, paper, paper2, settings, sse, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const title = 'Dense passage retrieval'

test('Given saved questions, When history renders, Then their mentions are pills named by their label and described by the citation, with no remove button; older questions stay plain text', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { papers: [included(paper), included(paper2)] })] },
    'GET /chats/c1/messages': {
      items: [
        { ...userMessage('u1', `How does ${title} train?`), mentions: [{ paper_id: 'p2', label: title, start: 9, end: 32 }] },
        assistantMessage('a1', 'With in-batch negatives.'),
        // Saved before pills carried the title: the label stays as it was sent.
        { ...userMessage('u2', 'And Karpukhin 2020?'), mentions: [{ paper_id: 'p2', label: 'Karpukhin 2020', start: 4, end: 18 }] },
        userMessage('u3', 'And @Author 2024?'),
      ],
    },
    'GET /papers/p2': paper2,
  })
  const { user } = mount('/papers/p1/chats/c1')
  const [first, older, plain] = await screen.findAllByRole('article', { name: 'Your message' })
  const pill = within(first!).getByRole('img', { name: title })
  await waitFor(() => expect(pill).toHaveAccessibleDescription('Karpukhin & Oguz (2020)'))
  expect(pill).toHaveAttribute('aria-roledescription', 'paper')
  // The pill sits in the sentence as sent; its hidden citation text only describes it.
  expect(first).toHaveTextContent(new RegExp(`^How does ${title}`))
  expect(first).toHaveTextContent(/ train\?$/)
  await user.hover(pill)
  expect(screen.queryByRole('button', { name: `Remove ${title}` })).not.toBeInTheDocument()
  expect(within(older!).getByRole('img', { name: 'Karpukhin 2020' })).toBeVisible()
  expect(within(plain!).queryByRole('img')).not.toBeInTheDocument()
  expect(plain).toHaveTextContent('And @Author 2024?')
})

test('Given a question that mentions a paper outside the chat, When its answer cites that paper, Then the answer is accepted', async () => {
  const cited: Citation = { chunk_id: '22222222-2222-4222-8222-222222222222', document_id: 'd2', paper_id: 'p2', page: 4, excerpt: 'Dense recall is 0.79.' }
  let papers = [included(paper)]
  mockApi({
    ...settings,
    'GET /chats': () => json({ items: [chatRow('c1', { papers })] }),
    'GET /chats/c1/messages': { items: [] },
    'GET /papers': { items: [paper, paper2] },
    'GET /papers/p2': paper2 satisfies Paper,
    'POST /chats/c1/messages/stream': () => {
      papers = [...papers, included(paper2)]
      return sse([['message.started', { message_id: 'm1' }], ['message.completed', assistantMessage('m1', `Dense recall is 0.79 [source:${cited.chunk_id}].`, { citations: [cited] })]])
    },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, 'What does @')
  await user.click(await screen.findByRole('option', { name: /Dense passage retrieval/ }))
  await within(input).findByRole('group', { name: title })
  await user.type(input, 'report?{Enter}')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  await waitFor(() => expect(reply).toHaveTextContent('Dense recall is 0.79'))
  expect(screen.queryByText(/source outside/)).not.toBeInTheDocument()
})
