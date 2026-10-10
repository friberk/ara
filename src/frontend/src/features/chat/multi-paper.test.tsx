// Chats over several library papers (ARA-088): the paper row of pills (ARA-110), the @ picker, routing and paper-named citations.
import { toast } from 'sonner'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Citation, Paper } from '@/api/types'
import { deletePill, isEditable, textIn } from '@/test/editor'
import { json, mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, included, luna, mount, paper, paper2, settings, userMessage } from './pane-test-kit'

vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }))

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })

const paper3: Paper = { ...paper2, id: 'p3', title: 'Late interaction retrieval', authors: ['Omar Khattab'], year: 2020, active_document_id: 'd3' }
const both = { paper_id: 'p1', papers: [included(paper), included(paper2)] }
const summary = (source: Paper, content: string) => ({ id: `s-${source.id}`, paper_id: source.id, document_id: source.active_document_id, model: 'gpt-5.6-luna', reasoning_effort: 'low', content, citations: [], created_at: '2026-10-08T09:00:00Z' })

function chips() { return screen.findByRole('list', { name: 'Papers in this conversation' }) }

async function removePill(user: ReturnType<typeof mount>['user'], list: HTMLElement, title: string) {
  await user.hover(within(list).getByRole('button', { name: title }))
  // user.click would first move the pointer onto the button, which user-event reports to React as leaving the pill.
  fireEvent.click(within(list).getByRole('button', { name: `Remove ${title} from this chat` }))
}

test('Given a chat over two papers, Then each shows as a composer pill, a click opens its reader tab, and no summary dialog or card appears (ARA-110)', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers/p1': paper,
    'GET /papers/p2': paper2,
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  const list = await chips()
  expect(within(list).getAllByRole('listitem')).toHaveLength(2)
  expect(within(list).getByRole('button', { name: 'Evidence based research' })).toBeVisible()
  await user.hover(within(list).getByRole('button', { name: 'Dense passage retrieval' }))
  await waitFor(() => expect(screen.getAllByText(/Karpukhin & Oguz/).some((node) => !node.closest('[hidden]'))).toBe(true))
  expect(screen.queryByText('Show summary')).not.toBeInTheDocument()
  await user.click(within(list).getByRole('button', { name: 'Dense passage retrieval' }))
  expect(workspace.showPaper).toHaveBeenLastCalledWith('p2')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.queryByRole('article', { name: 'Paper summary' })).not.toBeInTheDocument()
})

test('Given a chat over one paper, Then there is no paper row and its summary stays the first message', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [] }, 'GET /papers/p1/summaries': { items: [summary(paper, 'One paper summary.')] } })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByRole('article', { name: 'Paper summary' })).toBeVisible()
  expect(screen.queryByRole('list', { name: 'Papers in this conversation' })).not.toBeInTheDocument()
})

test('Given the paper in the URL is removed from the chat, Then the chat reroutes to its new first paper', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers/p1': paper,
    'GET /papers/p2': paper2,
    'DELETE /chats/c1/papers/p1': chatRow('c1', { paper_id: 'p2', papers: [included(paper2)] }),
  })
  const { user } = mount('/papers/p1/chats/c1', { others: [paper2] })
  const list = await chips()
  await removePill(user, list, 'Evidence based research')
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p2/chats/c1'))
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  // The last paper has no pill to remove: the row is gone.
  expect(screen.queryByRole('list', { name: 'Papers in this conversation' })).not.toBeInTheDocument()
})

test('Given a multi-paper chat opened from its second paper, Then its URL becomes its first paper', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', both)] }, 'GET /chats/c1/messages': { items: [] } })
  mount('/papers/p2/chats/c1', { value: paper2, others: [paper] })
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c1'))
  expect(await chips()).toBeVisible()
})

test('Given a chat link from a paper it no longer covers, Then the chat is found by id and opened at its first paper', async () => {
  mockApi({
    ...settings,
    'GET /chats': ({ url }) => json({ items: url.searchParams.get('paper_id') === 'p3' ? [] : [chatRow('c1', both)] }),
    'GET /chats/c1': chatRow('c1', both),
    'GET /chats/c1/messages': { items: [] },
  })
  mount('/papers/p3/chats/c1', { value: paper3, others: [paper] })
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c1'))
})

test('Given the chat composer, When @ mentions a paper outside the chat, Then it is a pill only while drafting and is sent with the question', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers': { items: [paper, paper2, paper3] },
    'GET /papers/p3': paper3,
    'POST /chats/c1/messages/stream': () => new Promise<Response>(() => {}),
  })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about these papers' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, 'How does @')
  expect(await screen.findByRole('option', { name: /Dense passage retrieval/ })).toHaveAttribute('aria-checked', 'true')
  await user.click(await screen.findByRole('option', { name: /Late interaction retrieval/ }))
  expect(await within(input).findByRole('group', { name: 'Late interaction retrieval' })).toHaveAccessibleDescription('Khattab (2020)')
  await waitFor(() => expect(input).toHaveFocus())
  // Not added and not a chip until the question is sent (ARA-096).
  expect(calls.some((call) => call.method === 'POST' && call.path === '/chats/c1/papers')).toBe(false)
  expect(within(await chips()).getAllByRole('listitem')).toHaveLength(2)
  await user.type(input, 'differ?{Enter}')
  await waitFor(() => expect(calls.find((call) => call.path === '/chats/c1/messages/stream')?.body).toMatchObject({ content: 'How does Late interaction retrieval differ?' }))
  expect((calls.find((call) => call.path === '/chats/c1/messages/stream')?.body as { mentions: unknown }).mentions).toEqual([{ paper_id: 'p3', label: 'Late interaction retrieval', start: 9, end: 35 }])
  // The sent question shows its pill.
  expect(await within(await screen.findByRole('article', { name: 'Your message' })).findByRole('img', { name: 'Late interaction retrieval' })).toBeVisible()
})

test('Given a pill for a paper outside the chat, When it is deleted before sending, Then the chat is unchanged and nothing is mentioned', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers': { items: [paper, paper2, paper3] },
    'POST /chats/c1/messages/stream': () => new Promise<Response>(() => {}),
  })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about these papers' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, 'Compare @')
  await user.click(await screen.findByRole('option', { name: /Late interaction retrieval/ }))
  await within(input).findByRole('group', { name: 'Late interaction retrieval' })
  deletePill(input, 0)
  await user.click(screen.getByRole('button', { name: 'Ask question' }))
  await waitFor(() => expect(calls.find((call) => call.path === '/chats/c1/messages/stream')?.body).toMatchObject({ content: 'Compare', mentions: [] }))
  expect(calls.some((call) => call.path === '/chats/c1/papers')).toBe(false)
})

test('Given an answer citing two papers and a removed one, Then each chip names its paper and page and asks the reader for that paper', async () => {
  const first: Citation = { chunk_id: '11111111-1111-4111-8111-111111111111', document_id: 'd1', paper_id: 'p1', page: 2, excerpt: 'Sparse recall is 0.61.' }
  const second: Citation = { chunk_id: '22222222-2222-4222-8222-222222222222', document_id: 'd2', paper_id: 'p2', page: 4, excerpt: 'Dense recall is 0.79.' }
  const removed: Citation = { chunk_id: '33333333-3333-4333-8333-333333333333', document_id: 'd3', paper_id: 'p3', page: 1, excerpt: 'Late interaction.' }
  const content = `Sparse reaches 0.61 [source:${first.chunk_id}]. Dense reaches 0.79 [source:${second.chunk_id}]. Late interaction helps [source:${removed.chunk_id}].`
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [userMessage('u1', 'Compare recall'), assistantMessage('m1', content, { citations: [first, second, removed] })] },
    'GET /papers/p1': paper,
    'GET /papers/p2': paper2,
    'GET /papers/p3': paper3,
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  const sources = await within(reply).findByRole('group', { name: 'Sources' })
  expect(await within(sources).findByRole('button', { name: 'Source, Author, 2024, page 2' })).toHaveTextContent(/^Author, 2024, p\. 2$/)
  expect(await within(sources).findByRole('button', { name: 'Source, Karpukhin & Oguz, 2020, page 4' })).toHaveTextContent(/^Karpukhin & Oguz, 2020, p\. 4$/)
  expect(await within(sources).findByRole('button', { name: 'Source, Khattab, 2020, page 1' })).toHaveTextContent(/^Khattab, 2020, p\. 1$/)
  expect(sources.textContent).not.toContain('·')
  expect(within(reply).queryByRole('alert')).not.toBeInTheDocument()
  await user.click(within(sources).getByRole('button', { name: 'Source, Karpukhin & Oguz, 2020, page 4' }))
  expect(workspace.showSource).toHaveBeenLastCalledWith(second, 'Dense reaches 0.79')
})

test('Given a chat over two papers and a streamed answer whose citations lack paper ids, Then the reader still learns each paper', async () => {
  const second: Citation = { chunk_id: '22222222-2222-4222-8222-222222222222', document_id: 'd2', page: 4, excerpt: 'Dense recall is 0.79.' }
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /papers/p1': paper,
    'GET /papers/p2': paper2,
    'GET /chats/c1/messages': { items: [userMessage('u1', 'Dense?'), assistantMessage('m1', `Dense reaches 0.79 [source:${second.chunk_id}].`, { citations: [second] })] },
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  const sources = await within(reply).findByRole('group', { name: 'Sources' })
  await user.click(await within(sources).findByRole('button', { name: 'Source, Karpukhin & Oguz, 2020, page 4' }))
  expect(workspace.showSource).toHaveBeenLastCalledWith({ ...second, paper_id: 'p2' }, 'Dense reaches 0.79')
})

test('Given a new conversation, When a second paper is mentioned with @, Then the first question creates one chat over both and sends its pills', async () => {
  let created = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': () => json({ items: created ? [chatRow('c9', both)] : [] }),
    'GET /papers': { items: [paper, paper2] },
    'GET /papers/p1': paper,
    'GET /papers/p2': paper2,
    'POST /chats': () => { created = true; return json(chatRow('c9', both), 201) },
    'POST /chats/c9/messages/stream': () => new Promise<Response>(() => {}),
  })
  const { user } = mount('/papers/p1')
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, '@')
  await user.click(await screen.findByRole('option', { name: /Dense passage retrieval/ }))
  const question = screen.getByRole('textbox', { name: 'Question about these papers' })
  await waitFor(() => expect(textIn(question)).toBe('Dense passage retrieval '))
  // The pills are the attachments: no chip row above the question (ARA-096).
  expect(screen.queryByRole('button', { name: /^Remove / })).not.toBeInTheDocument()
  // Typing @ again and choosing the conversation's own paper only mentions it.
  await user.type(question, 'or @')
  await user.click(await screen.findByRole('option', { name: /Evidence based research/ }))
  await waitFor(() => expect(textIn(question)).toBe('Dense passage retrieval or Evidence based research '))
  await user.type(question, 'How do they compare?{Enter}')
  await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/chats')?.body).toEqual({ paper_ids: ['p1', 'p2'] }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c9'))
  await waitFor(() => expect(calls.find((call) => call.path === '/chats/c9/messages/stream')?.body).toMatchObject({
    content: 'Dense passage retrieval or Evidence based research How do they compare?',
    mentions: [{ paper_id: 'p2', label: 'Dense passage retrieval', start: 0, end: 23 }, { paper_id: 'p1', label: 'Evidence based research', start: 27, end: 50 }],
  }))
})

test('Given a new conversation, When the only pill of an added paper is deleted, Then the paper leaves the conversation', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [] }, 'GET /papers': { items: [paper, paper2] } })
  const { user } = mount('/papers/p1')
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, 'Compare @')
  await user.click(await screen.findByRole('option', { name: /Dense passage retrieval/ }))
  expect(screen.getByRole('textbox', { name: 'Question about these papers' })).toBe(input)
  await within(input).findByRole('group', { name: 'Dense passage retrieval' })
  deletePill(input, 0)
  expect(screen.getByRole('textbox', { name: 'Question about this paper' })).toBe(input)
})

test('Given a local model selected in a chat over two papers, Then the composer asks for a hosted model before sending', async () => {
  const local = { ...luna, key: 'ifm-local', provider: 'ollama', display_name: 'IFM local', reasoning_efforts: ['default'] }
  mockApi({
    'GET /features': { open_models: true },
    'GET /models': { items: [local, luna] },
    'GET /settings': { default_model: local.key, reasoning_effort: 'default' },
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  expect(await screen.findByText('Chats over several papers need a hosted model. Choose one below.')).toBeVisible()
  await user.type(screen.getByRole('textbox', { name: 'Question about these papers' }), 'Compare them')
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
})

test('Given a chat over fifteen papers, Then three pills show and a +12 pill opens the rest as the same pills, any of which can be removed', async () => {
  const many = Array.from({ length: 15 }, (_, n) => included({ ...paper2, id: `m${n}`, title: `Study ${n}`, active_document_id: `md${n}` }))
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { papers: [included(paper), ...many.slice(1)] })] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers/p1': paper,
    ...Object.fromEntries(many.map((item) => [`GET /papers/${item.paper_id}`, { ...paper2, id: item.paper_id, title: item.title }])),
    'DELETE /chats/c1/papers/m9': chatRow('c1', { papers: [included(paper), ...many.slice(1).filter((item) => item.paper_id !== 'm9')] }),
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  const list = await chips()
  expect(within(list).getAllByRole('listitem')).toHaveLength(4)
  await user.click(within(list).getByRole('button', { name: '+12 more papers' }))
  const rest = await screen.findByRole('list', { name: 'More papers in this conversation' })
  expect(within(rest).getAllByRole('listitem')).toHaveLength(12)
  expect(within(rest).queryByRole('button', { name: 'Study 1' })).toBeNull()
  await user.click(within(rest).getByRole('button', { name: 'Study 5' }))
  expect(workspace.showPaper).toHaveBeenLastCalledWith('m5')
  await removePill(user, rest, 'Study 9')
  await waitFor(() => expect(calls.filter((call) => call.method === 'DELETE' && call.path === '/chats/c1/papers/m9')).toHaveLength(1))
})

test('Given a paper already in the chat, When its pill is deleted, Then it stays; removing it from the chat removes its pills', async () => {
  let papers = [included(paper), included(paper2)]
  const { calls } = mockApi({
    ...settings,
    'GET /chats': () => json({ items: [chatRow('c1', { papers })] }),
    'GET /chats/c1/messages': { items: [] },
    'GET /papers': { items: [paper, paper2] },
    'GET /papers/p1': paper,
    'GET /papers/p2': paper2,
    'DELETE /chats/c1/papers/p2': () => { papers = papers.filter((item) => item.paper_id !== 'p2'); return json(chatRow('c1', { papers })) },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about these papers' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.type(input, 'What does @')
  // The typed-@ picker mentions papers: included ones are checked, and choosing one only mentions it.
  expect(await screen.findByPlaceholderText('Mention a paper')).toBeVisible()
  const dense = await screen.findByRole('option', { name: /Dense passage retrieval/ })
  expect(dense).toHaveAttribute('aria-checked', 'true')
  await user.click(dense)
  await waitFor(() => expect(textIn(input)).toBe('What does Dense passage retrieval '))
  await within(input).findByRole('group', { name: 'Dense passage retrieval' })
  deletePill(input, 0)
  expect(within(input).queryByRole('group')).not.toBeInTheDocument()
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
  expect(within(await chips()).getAllByRole('listitem')).toHaveLength(2)
  // Mentioned again, then removed with its chip above the chat: the paper leaves the chat and its pill the question.
  await user.type(input, '@')
  await user.click(await screen.findByRole('option', { name: /Dense passage retrieval/ }))
  await within(input).findByRole('group', { name: 'Dense passage retrieval' })
  await removePill(user, await chips(), 'Dense passage retrieval')
  await waitFor(() => expect(calls.filter((call) => call.method === 'DELETE' && call.path === '/chats/c1/papers/p2')).toHaveLength(1))
  await waitFor(() => expect(within(input).queryByRole('group')).not.toBeInTheDocument())
})

test('Given the chat composer, When the @ button is used, Then the paper becomes a pill at the end of the question and nothing is added before sending', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers': { items: [paper, paper2, paper3] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about these papers' })
  await waitFor(() => expect(isEditable(input)).toBe(true))
  await user.click(screen.getByRole('button', { name: 'Mention a paper' }))
  await user.click(await screen.findByRole('option', { name: /Late interaction retrieval/ }))
  expect(await within(input).findByRole('group', { name: 'Late interaction retrieval' })).toBeInTheDocument()
  await waitFor(() => expect(input).toHaveFocus())
  expect(calls.some((call) => call.method !== 'GET')).toBe(false)
  expect(within(await chips()).getAllByRole('listitem')).toHaveLength(2)
})

describe('removing a paper from the row (ARA-110)', () => {
  function removable(extra: Record<string, unknown> = {}) {
    let papers = [included(paper), included(paper2)]
    return mockApi({
      ...settings,
      'GET /chats': () => json({ items: [chatRow('c1', { papers })] }),
      'GET /chats/c1/messages': { items: [] },
      'GET /papers/p1': paper,
      'GET /papers/p2': paper2,
      'DELETE /chats/c1/papers/p2': () => { papers = papers.filter((item) => item.paper_id !== 'p2'); return json(chatRow('c1', { papers })) },
      'POST /chats/c1/papers': () => { papers = [...papers, included(paper2)]; return json(chatRow('c1', { papers })) },
      ...extra,
    })
  }
  const undoOf = () => (vi.mocked(toast).mock.calls[0]![1] as { action: { label: string; onClick: () => void } }).action

  test('Given a pill in the row, Then its × says it removes the paper from the chat', async () => {
    removable()
    const { user } = mount('/papers/p1/chats/c1')
    const list = await chips()
    await user.hover(within(list).getByRole('button', { name: 'Dense passage retrieval' }))
    expect(within(list).getByRole('button', { name: 'Remove Dense passage retrieval from this chat' })).toBeVisible()
  })

  test('Given a removal succeeds, Then a toast says so with an Undo action, and focus moves to the next pill', async () => {
    removable()
    const { user } = mount('/papers/p1/chats/c1')
    const list = await chips()
    await removePill(user, list, 'Dense passage retrieval')
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Removed from this chat', expect.objectContaining({ action: expect.objectContaining({ label: 'Undo' }) })))
  })

  test('Given the removed paper had a pill before another, Then focus lands on the pill that follows', async () => {
    const three = Array.from({ length: 3 }, (_, n) => included({ ...paper2, id: `t${n}`, title: `Third ${n}`, active_document_id: `td${n}` }))
    let papers = three
    mockApi({
      ...settings,
      'GET /chats': () => json({ items: [chatRow('c1', { paper_id: 't0', papers })] }),
      'GET /chats/c1/messages': { items: [] },
      ...Object.fromEntries(three.map((item) => [`GET /papers/${item.paper_id}`, { ...paper2, id: item.paper_id, title: item.title }])),
      'DELETE /chats/c1/papers/t1': () => { papers = papers.filter((item) => item.paper_id !== 't1'); return json(chatRow('c1', { paper_id: 't0', papers })) },
    })
    const { user } = mount('/papers/t0/chats/c1', { value: { ...paper2, id: 't0' } })
    const list = await chips()
    await removePill(user, list, 'Third 1')
    await waitFor(() => expect(within(list).getByRole('button', { name: 'Third 2' })).toHaveFocus())
  })

  test('Given Undo is pressed, Then the paper is added back through the chat and its pill returns', async () => {
    const { calls } = removable()
    const { user } = mount('/papers/p1/chats/c1')
    const list = await chips()
    await removePill(user, list, 'Dense passage retrieval')
    await waitFor(() => expect(toast).toHaveBeenCalled())
    undoOf().onClick()
    await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/chats/c1/papers')?.body).toEqual({ paper_id: 'p2' }))
    expect(await within(await chips()).findByRole('button', { name: 'Dense passage retrieval' })).toBeVisible()
  })

  test('Given Undo fails, Then an error toast says the paper could not be added back', async () => {
    removable({ 'POST /chats/c1/papers': () => json({ detail: 'The PDF is not ready.' }, 409) })
    const { user } = mount('/papers/p1/chats/c1')
    await removePill(user, await chips(), 'Dense passage retrieval')
    await waitFor(() => expect(toast).toHaveBeenCalled())
    undoOf().onClick()
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Dense passage retrieval')))
    expect(vi.mocked(toast.error).mock.calls[0]![0]).toMatch(/back in this chat/)
  })
})
