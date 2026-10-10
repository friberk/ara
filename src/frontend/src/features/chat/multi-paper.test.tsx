// Chats over several library papers (ARA-088): paper chips, the @ picker, routing and paper-named citations.
import { screen, waitFor, within } from '@testing-library/react'
import type { Citation, Paper } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, included, luna, mount, paper, paper2, settings, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const paper3: Paper = { ...paper2, id: 'p3', title: 'Late interaction retrieval', authors: ['Omar Khattab'], year: 2020, active_document_id: 'd3' }
const both = { paper_id: 'p1', papers: [included(paper), included(paper2)] }
const summary = (source: Paper, content: string) => ({ id: `s-${source.id}`, paper_id: source.id, document_id: source.active_document_id, model: 'gpt-5.6-luna', reasoning_effort: 'low', content, citations: [], created_at: '2026-10-08T09:00:00Z' })

function chips() { return screen.findByRole('list', { name: 'Papers in this conversation' }) }

test('Given a chat over two papers, Then both show as chips, each summary opens from its chip, and no summary card is stacked in the thread', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'GET /papers/p2': paper2,
    'GET /papers/p2/summaries': { items: [summary(paper2, 'Dense retrieval beats BM25 on recall.')] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const list = await chips()
  expect(within(list).getAllByRole('listitem')).toHaveLength(2)
  expect(within(list).getByRole('button', { name: 'Evidence based research' })).toBeVisible()
  expect(screen.queryByRole('article', { name: 'Paper summary' })).not.toBeInTheDocument()
  await user.click(within(list).getByRole('button', { name: 'Dense passage retrieval' }))
  const dialog = await screen.findByRole('dialog', { name: 'Dense passage retrieval' })
  expect(await within(dialog).findByText('Dense retrieval beats BM25 on recall.')).toBeVisible()
  expect(within(dialog).getByText('Karpukhin et al., 2020')).toBeVisible()
})

test('Given a chat over one paper, Then its chip cannot be removed and its summary stays the first message', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [] }, 'GET /papers/p1/summaries': { items: [summary(paper, 'One paper summary.')] } })
  mount('/papers/p1/chats/c1')
  const list = await chips()
  expect(within(list).getAllByRole('listitem')).toHaveLength(1)
  expect(within(list).queryByRole('button', { name: /^Remove/ })).not.toBeInTheDocument()
  expect(await screen.findByRole('article', { name: 'Paper summary' })).toBeVisible()
})

test('Given the paper in the URL is removed from the chat, Then the chat reroutes to its new first paper', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [] },
    'DELETE /chats/c1/papers/p1': chatRow('c1', { paper_id: 'p2', papers: [included(paper2)] }),
  })
  const { user } = mount('/papers/p1/chats/c1', { others: [paper2] })
  const list = await chips()
  await user.click(within(list).getByRole('button', { name: 'Remove Evidence based research from this conversation' }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p2/chats/c1'))
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
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

test('Given the chat composer, When @ is typed, Then the library picker adds a paper or removes an included one', async () => {
  let papers = [included(paper), included(paper2)]
  const { calls } = mockApi({
    ...settings,
    'GET /chats': () => json({ items: [chatRow('c1', { papers })] }),
    'GET /chats/c1/messages': { items: [] },
    'GET /papers': { items: [paper, paper2, paper3] },
    'POST /chats/c1/papers': () => { papers = [...papers, included(paper3)]; return json(chatRow('c1', { papers })) },
    'DELETE /chats/c1/papers/p2': () => { papers = papers.filter((item) => item.paper_id !== 'p2'); return json(chatRow('c1', { papers })) },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const input = await screen.findByRole('textbox', { name: 'Question about these papers' })
  await waitFor(() => expect(input).toBeEnabled())
  await user.type(input, '@')
  expect(input).toHaveValue('')
  const added = await screen.findByRole('option', { name: /Dense passage retrieval/ })
  expect(added).toHaveTextContent('Added. Choose again to remove.')
  await user.click(await screen.findByRole('option', { name: /Late interaction retrieval/ }))
  await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/chats/c1/papers')?.body).toEqual({ paper_id: 'p3' }))
  await waitFor(async () => expect(within(await chips()).getAllByRole('listitem')).toHaveLength(3))
  await user.click(screen.getByRole('button', { name: 'Add or remove papers' }))
  await user.click(await screen.findByRole('option', { name: /Dense passage retrieval/ }))
  await waitFor(async () => expect(within(await chips()).getAllByRole('listitem')).toHaveLength(2))
  expect(calls.filter((call) => call.method === 'DELETE' && call.path === '/chats/c1/papers/p2')).toHaveLength(1)
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
    'GET /papers/p3': paper3,
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  const sources = await within(reply).findByRole('group', { name: 'Sources' })
  expect(within(sources).getByRole('button', { name: 'Source, Author 2024, page 2' })).toHaveTextContent('Author 2024 · p. 2')
  expect(within(sources).getByRole('button', { name: 'Source, Karpukhin 2020, page 4' })).toHaveTextContent('Karpukhin 2020 · p. 4')
  expect(await within(sources).findByRole('button', { name: 'Source, Khattab 2020, page 1' })).toHaveTextContent('Khattab 2020 · p. 1')
  expect(within(reply).queryByRole('alert')).not.toBeInTheDocument()
  await user.click(within(sources).getByRole('button', { name: 'Source, Karpukhin 2020, page 4' }))
  expect(workspace.showSource).toHaveBeenLastCalledWith(second, 'Dense reaches 0.79')
})

test('Given a chat over two papers and a streamed answer whose citations lack paper ids, Then the reader still learns each paper', async () => {
  const second: Citation = { chunk_id: '22222222-2222-4222-8222-222222222222', document_id: 'd2', page: 4, excerpt: 'Dense recall is 0.79.' }
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', both)] },
    'GET /chats/c1/messages': { items: [userMessage('u1', 'Dense?'), assistantMessage('m1', `Dense reaches 0.79 [source:${second.chunk_id}].`, { citations: [second] })] },
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  const sources = await within(reply).findByRole('group', { name: 'Sources' })
  await user.click(within(sources).getByRole('button', { name: 'Source, Karpukhin 2020, page 4' }))
  expect(workspace.showSource).toHaveBeenLastCalledWith({ ...second, paper_id: 'p2' }, 'Dense reaches 0.79')
})

test('Given a new conversation, When a second paper is added with @, Then the first question creates one chat over both', async () => {
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [] },
    'GET /papers': { items: [paper, paper2] },
    'POST /chats': () => json(chatRow('c9', both), 201),
    'POST /chats/c9/messages/stream': () => new Promise<Response>(() => {}),
  })
  const { user } = mount('/papers/p1')
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(input).toBeEnabled())
  await user.type(input, '@')
  await user.click(await screen.findByRole('option', { name: /Dense passage retrieval/ }))
  const question = screen.getByRole('textbox', { name: 'Question about these papers' })
  expect(screen.getByRole('button', { name: 'Remove Dense passage retrieval' })).toBeVisible()
  await user.type(question, 'How do they compare?{Enter}')
  await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/chats')?.body).toEqual({ paper_ids: ['p1', 'p2'] }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c9'))
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
