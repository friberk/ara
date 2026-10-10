// "How this answer was found" (ARA-075): a saved answer explains its search, passages and context on request.
import { screen, within } from '@testing-library/react'
import type { ContextUsage, RetrievalSummary } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, mount, settings, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const hybrid: RetrievalSummary = { mode: 'hybrid', profile: 'openai-3-large', reranked: false, standalone_query: 'What recall did BM25 reach on Natural Questions?', search_queries: ['BM25 recall Natural Questions'], passages_found: 12, passages_used: 6, limited_by_context: false, note: null, pruned: 0, evidence_tokens: 0, summaries_used: 0, retried: false, map_reduce: false }
const usage: ContextUsage = { window: 8192, input_tokens: 5120, output_reserved: 2048, summary_version: null, recent_turns: 4, recalled_turns: 0, truncated: false }

function showAnswer(overrides: Record<string, unknown>) {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': { items: [userMessage('u1', 'What recall did BM25 reach?'), assistantMessage('m1', 'BM25 reached 71.2 recall.', overrides)] } })
  return mount('/papers/p1/chats/c1')
}
async function openDetails(user: ReturnType<typeof showAnswer>['user']) {
  const answer = await screen.findByRole('article', { name: 'Assistant message' })
  await user.click(within(answer).getByRole('button', { name: 'Details' }))
  return screen.findByRole('dialog', { name: 'How this answer was found' })
}

test('Given a hybrid answer, When Details is opened, Then it names the query, the search, reranking, passages and context in plain words', async () => {
  const { user } = showAnswer({ retrieval: hybrid, context: usage, grounding: 'supported' })
  const details = await openDetails(user)
  const rows = within(details).getAllByRole('listitem').map((row) => row.textContent)
  expect(rows).toEqual([
    'Searched for “What recall did BM25 reach on Natural Questions?”',
    'Keyword and meaning search',
    'Results were not reranked',
    'Used 6 of 12 relevant passages',
    'Context: 5,120 of 8,192 tokens',
  ])
  expect(screen.queryByText(/enough evidence/)).not.toBeInTheDocument()
})

test('Given a local answer under its input cap, When Details is opened, Then context is counted against that cap, not the window', async () => {
  const { user } = showAnswer({ retrieval: hybrid, context: { ...usage, input_tokens: 2900, input_budget: 3072 } })
  const details = await openDetails(user)
  expect(within(details).getByText('Context: 2,900 of 3,072 tokens')).toBeInTheDocument()
})

test('Given a keyword-only answer limited by context after a summary, When Details is opened, Then it says so with the note and the model name', async () => {
  const keyword: RetrievalSummary = { ...hybrid, mode: 'keyword', reranked: true, standalone_query: null, search_queries: ['BM25 recall', 'Natural Questions recall'], passages_found: 20, passages_used: 5, limited_by_context: true, note: 'Meaning search starts once this paper’s search index is ready.' }
  const { user } = showAnswer({ retrieval: keyword, context: { ...usage, input_tokens: 7900, summary_version: 2 } })
  const details = await openDetails(user)
  const rows = within(details).getAllByRole('listitem').map((row) => row.textContent)
  expect(rows).toEqual([
    'Searched for “BM25 recall”',
    'Keyword search. Meaning search starts once this paper’s search index is ready.',
    'Results were reranked',
    'Used 5 of 20 relevant passages (limited by Luna’s context)',
    'Context: 7,900 of 8,192 tokens (earlier messages summarized)',
  ])
})

test('Given an answer saved before retrieval details existed, Then no Details button is offered', async () => {
  showAnswer({})
  const answer = await screen.findByRole('article', { name: 'Assistant message' })
  expect(within(answer).getByRole('button', { name: 'Copy answer' })).toBeVisible()
  expect(within(answer).queryByRole('button', { name: 'Details' })).not.toBeInTheDocument()
})

test('Given an answer without context usage, When Details is opened, Then the context row is left out', async () => {
  const { user } = showAnswer({ retrieval: hybrid, context: null })
  const details = await openDetails(user)
  expect(within(details).getAllByRole('listitem').map((row) => row.textContent)).not.toContainEqual(expect.stringMatching(/^Context/))
})

test('Given the paper lacks evidence for the question, Then the answer carries a quiet note saying so', async () => {
  showAnswer({ retrieval: hybrid, context: usage, grounding: 'insufficient' })
  const answer = await screen.findByRole('article', { name: 'Assistant message' })
  expect(within(answer).getByText('The paper doesn’t contain enough evidence for this.')).toBeVisible()
  expect(within(answer).queryByRole('alert')).not.toBeInTheDocument()
})

test('Given an answer from relevance-driven evidence, When Details is opened, Then it shows the passages, their tokens, what was pruned and the wider retry (ARA-094)', async () => {
  const driven = { ...hybrid, passages_used: 9, evidence_tokens: 4210, pruned: 7, summaries_used: 2, retried: true, map_reduce: false }
  const { user } = showAnswer({ retrieval: driven, context: usage, grounding: 'supported' })
  const details = await openDetails(user)
  const rows = within(details).getAllByRole('listitem').map((row) => row.textContent)
  expect(rows).toEqual([
    'Searched for “What recall did BM25 reach on Natural Questions?”',
    'Keyword and meaning search',
    'Results were not reranked',
    'Used 9 of 12 relevant passages, 4,210 tokens',
    'Included 2 section summaries',
    'Left out 7 passages that scored far below the best one',
    'The first answer found too little, so the search was widened once',
    'Context: 5,120 of 8,192 tokens',
  ])
})

test('Given a small window that read each paper apart, When Details is opened, Then it says so', async () => {
  const mapped = { ...hybrid, evidence_tokens: 900, pruned: 0, summaries_used: 0, retried: false, map_reduce: true }
  const { user } = showAnswer({ retrieval: mapped, context: usage })
  const details = await openDetails(user)
  const rows = within(details).getAllByRole('listitem').map((row) => row.textContent)
  expect(rows).toContain('Read each paper in its own request, then combined the notes')
  expect(rows).not.toContainEqual(expect.stringMatching(/^Left out|^Included|widened/))
})
