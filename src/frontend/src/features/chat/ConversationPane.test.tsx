import { StrictMode } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom'
import type { Citation, Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { MarkdownProps, SourceListProps } from '@/features/content'
import { WorkspaceContext, type WorkspaceContextValue } from '@/features/workspace/workspace-context'
import { json, mockApi } from '@/test/fetch-routes'
import { testClient } from '@/test/render'
import { ConversationPane } from '.'

// The content module (ARA-035) is rebuilt in parallel. These stand-ins honour its documented props, so the
// tests pin this pane's wiring: which document scopes the citations and where a chip sends the reader.
vi.mock('@/features/content', () => ({
  Markdown: ({ content, citations = [], documentId, onCitation }: MarkdownProps) => (
    <div>
      <p>{content.replace(/\[source:[0-9a-f-]{36}\]/gi, '')}</p>
      {citations.filter((citation) => citation.document_id === documentId).map((citation) => <button key={citation.chunk_id} type="button" onClick={() => onCitation?.(citation)}>Inline page {citation.page}</button>)}
    </div>
  ),
  SourceList: ({ citations, documentId, onSelect }: SourceListProps) => (
    <div aria-label="Sources">{citations.filter((citation) => citation.document_id === documentId).map((citation) => <button key={citation.chunk_id} type="button" onClick={() => onSelect?.(citation)}>Page {citation.page}</button>)}</div>
  ),
  CitationChip: () => null,
}))

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const settings = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } }
const citation: Citation = { chunk_id: 'chunk1', document_id: 'd1', page: 2, excerpt: 'A measured result from the document.' }
const marker = '[source:12345678-1234-1234-1234-123456789abc]'
function chatRow(id: string, overrides: Record<string, unknown> = {}) {
  return { id, paper_id: 'p1', document_id: 'd1', title: 'Research question', title_source: 'auto', created_at: '2026-10-08T10:00:00Z', paper_title: paper.title, last_activity_at: '2026-10-08T12:00:00Z', message_count: 0, last_question_preview: null, ...overrides }
}
function userMessage(id: string, content: string) { return { id, role: 'user', content, state: 'completed', model: null, reasoning_effort: null, citations: [], created_at: '2026-10-08T12:00:00Z' } }
function assistantMessage(id: string, content: string, overrides: Record<string, unknown> = {}) {
  return { id, role: 'assistant', content, state: 'completed', model: luna.key, reasoning_effort: 'low', citations: [], created_at: '2026-10-08T12:00:01Z', ...overrides }
}
function sse(frames: [string, unknown][]) {
  return new Response(frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}
function workspaceValue(): WorkspaceContextValue {
  return { paper, view: 'chat', setView: vi.fn(), readerTab: 'pdf', setReaderTab: vi.fn(), sourceRequest: null, showSource: vi.fn(), highlightOutcome: null, reportHighlight: vi.fn() }
}

function PaneRoute({ value }: { value: Paper }) {
  const { chatId } = useParams()
  return <ConversationPane paper={value} chatId={chatId} />
}
function CurrentPath() { return <output aria-label="Current path">{useLocation().pathname}</output> }
function mount(path: string, { value = paper, workspace = workspaceValue(), strict = false }: { value?: Paper; workspace?: WorkspaceContextValue; strict?: boolean } = {}) {
  const client = testClient()
  const user = userEvent.setup()
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TooltipProvider>
          <GenerationSettingsProvider>
            <WorkspaceContext.Provider value={workspace}>
              <div style={{ height: 800 }}>
                <Routes>
                  <Route path="/papers/:paperId" element={<PaneRoute value={value} />} />
                  <Route path="/papers/:paperId/chats/:chatId" element={<PaneRoute value={value} />} />
                </Routes>
              </div>
              <CurrentPath />
            </WorkspaceContext.Provider>
          </GenerationSettingsProvider>
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
  render(strict ? <StrictMode>{tree}</StrictMode> : tree)
  return { user, client, workspace }
}
async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(input).toBeEnabled())
  await user.type(input, question)
  await user.click(screen.getByRole('button', { name: 'Ask question' }))
}
afterEach(() => vi.unstubAllGlobals())

test('Given a ready chat, When a question streams, Then the answer cites page 2 and its chips open the source in the reader', async () => {
  const answer = assistantMessage('m1', `The measured result is grounded.${marker}`, { citations: [citation] })
  let answered = false
  const { calls } = mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1')] },
    'GET /chats/c1/messages': () => json({ items: answered ? [userMessage('u1', 'What was measured?'), answer] : [] }),
    'POST /chats/c1/messages/stream': () => { answered = true; return sse([['message.started', { message_id: 'm1' }], ['message.delta', { text: 'The measured result is grounded.' }], ['message.completed', answer]]) },
  })
  const { user, workspace } = mount('/papers/p1/chats/c1')
  await ask(user, 'What was measured?')
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  expect(await within(reply).findByText('The measured result is grounded.')).toBeVisible()
  expect(screen.getByRole('article', { name: 'Your message' })).toHaveTextContent('What was measured?')
  await waitFor(() => expect(screen.getAllByRole('article', { name: 'Your message' })).toHaveLength(1))
  await user.click(within(within(reply).getByLabelText('Sources')).getByRole('button', { name: 'Page 2' }))
  expect(workspace.showSource).toHaveBeenCalledWith(citation)
  await user.click(within(reply).getByRole('button', { name: 'Inline page 2' }))
  expect(workspace.showSource).toHaveBeenCalledTimes(2)
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
