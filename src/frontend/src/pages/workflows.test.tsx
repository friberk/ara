import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '../App'

const paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'metadata_only', active_document_id: null, metadata_provenance: {} }
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function mount(path: string) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>); return client }
afterEach(() => vi.unstubAllGlobals())

test('Given search results, When saved, Then the paper can be opened in the library', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/search?')) return response({ provider: 'openalex', items: [{ provider: 'openalex', external_id: 'W1', title: paper.title, authors: paper.authors, year: 2024, abstract: null, doi: null, external_url: null, pdf_url: null }], next_cursor: 'page2', total: 1 })
    if (url.endsWith('/papers') && init?.method === 'POST') return response(paper)
    return response({ items: [] })
  }))
  mount('/search')
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: 'Research topic' }), 'retrieval')
  await user.click(screen.getByRole('button', { name: 'Search papers' }))
  expect(await screen.findByRole('heading', { name: paper.title })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Save to library' }))
  expect(await screen.findByRole('link', { name: 'Open paper' })).toHaveAttribute('href', '/papers/p1')
  expect(screen.getByRole('button', { name: 'Load more' })).toBeVisible()
})

test('Given a provider limit, When searching, Then recovery is shown', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ code: 'rate_limited', message: 'Provider is busy. Try again later.', request_id: 'r1' }, 429)))
  mount('/search'); const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: 'Research topic' }), 'graphs')
  await user.click(screen.getByRole('button', { name: 'Search papers' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Provider is busy')
})

test('Given metadata only, Then analysis stays disabled and PDF upload is offered', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/papers/p1') ? response(paper) : response({ items: [] })))
  mount('/papers/p1')
  expect(await screen.findByRole('heading', { name: paper.title })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Generate summary' })).toBeDisabled()
  expect(screen.getByLabelText('PDF file')).toBeVisible()
  expect(screen.getByText(/Upload a PDF to enable/)).toBeVisible()
})

test('Given a PDF upload accepted, Then the durable processing status is shown', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/documents') && init?.method === 'POST') return response({ paper_id: 'p1', document_id: 'd1', job_id: 'j1' }, 202)
    if (url.endsWith('/jobs/j1')) return response({ id: 'j1', kind: 'ingest', state: 'processing', stage: 'extracting', progress: 40, attempts: 1, error: null, result: null })
    return response({ items: [] })
  }))
  mount('/library'); const user = userEvent.setup()
  await user.upload(screen.getByLabelText('PDF file'), new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  expect(await screen.findByText(/extracting/)).toBeVisible()
  await waitFor(() => expect(screen.getByRole('link', { name: 'Open uploaded paper' })).toHaveAttribute('href', '/papers/p1'))
})

test('Given unavailable and supported models, Then exact IDs and reasoning capabilities govern selection', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/settings') ? response({ default_model: 'gpt-5.6-luna', reasoning_effort: 'low' }) : response({ items: [{ key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }, { key: 'unavailable-exact', provider: 'openai', model_id: 'unavailable-exact', display_name: 'Unavailable model', status: 'unavailable', reasoning_efforts: [], supports_streaming: false, supports_structured_output: false, context_window: 32000 }] })))
  mount('/settings')
  const model = await screen.findByRole('combobox', { name: 'Model' })
  await waitFor(() => expect(model).toHaveValue('gpt-5.6-luna'))
  expect(screen.getByRole('option', { name: /Unavailable model/ })).toBeDisabled()
  expect(screen.getByRole('combobox', { name: 'Reasoning effort' })).toHaveValue('low')
  expect(screen.getByRole('option', { name: 'high' })).toBeVisible()
})

test('Given a ready paper, When a question streams, Then history and a genuine page citation can be inspected', async () => {
  const ready = { ...paper, document_status: 'ready', active_document_id: 'd1' }
  const model = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
  const citation = { chunk_id: 'chunk1', document_id: 'd1', page: 2, excerpt: 'A measured result from the document.' }
  const answer = { id: 'm1', role: 'assistant', content: 'The measured result is grounded.[source:12345678-1234-1234-1234-123456789abc]', state: 'completed', model: model.key, reasoning_effort: 'low', citations: [citation], created_at: '2026-10-08T00:00:00Z' }
  let completed = false
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/papers/p1')) return response(ready)
    if (url.endsWith('/models')) return response({ items: [model] })
    if (url.endsWith('/settings')) return response({ default_model: model.key, reasoning_effort: 'low' })
    if (url.endsWith('/papers/p1/chats')) return response({ items: [{ id: 'c1', paper_id: 'p1', document_id: 'd1', title: 'Research question', created_at: '2026-10-08T00:00:00Z' }] })
    if (url.endsWith('/chats/c1/messages/stream')) { completed = true; return new Response(`event: message.started\ndata: {"message_id":"m1"}\n\nevent: message.delta\ndata: {"text":"The measured result is grounded."}\n\nevent: message.completed\ndata: ${JSON.stringify(answer)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }) }
    if (url.endsWith('/chats/c1/messages')) return response({ items: completed ? [answer] : [] })
    if (url.endsWith('/documents/d1/chunks/chunk1')) return response(citation)
    return response({ items: [] })
  }))
  mount('/papers/p1'); const user = userEvent.setup()
  await screen.findByRole('heading', { name: paper.title })
  await user.click(screen.getByRole('tab', { name: 'Questions' }))
  await user.click(await screen.findByRole('button', { name: 'Research question' }))
  await user.type(await screen.findByRole('textbox', { name: 'Question about this paper' }), 'What was measured?')
  await user.click(screen.getByRole('button', { name: 'Ask question' }))
  expect(await screen.findByText('The measured result is grounded.')).toBeVisible()
  expect(screen.queryByText(/\[source:12345678-1234-1234-1234-123456789abc\]/)).not.toBeInTheDocument()
  await user.click(await screen.findByRole('button', { name: 'Page 2' }))
  expect(await screen.findByRole('dialog', { name: 'Source · page 2' })).toHaveTextContent(citation.excerpt)
  expect(screen.getByRole('link', { name: 'Open PDF at page 2' })).toHaveAttribute('href', '/api/v1/documents/d1/download#page=2')
})

test('Given a streaming response, When stopped, Then persisted interrupted content remains and no paid retry occurs', async () => {
  const ready = { ...paper, document_status: 'ready', active_document_id: 'd1' }
  const model = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
  let stopped = false; let generationRequests = 0
  const message = { id: 'm2', role: 'assistant', content: 'Partial evidence', state: 'interrupted', model: model.key, reasoning_effort: 'low', citations: [], created_at: '2026-10-08T00:00:00Z' }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/papers/p1')) return response(ready)
    if (url.endsWith('/models')) return response({ items: [model] })
    if (url.endsWith('/settings')) return response({ default_model: model.key, reasoning_effort: 'low' })
    if (url.endsWith('/papers/p1/chats')) return response({ items: [{ id: 'c2', paper_id: 'p1', document_id: 'd1', title: 'Stop example', created_at: '2026-10-08T00:00:00Z' }] })
    if (url.endsWith('/chats/c2/messages/stream')) {
      generationRequests++
      const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode('event: message.started\ndata: {"message_id":"m2"}\n\nevent: message.delta\ndata: {"text":"Partial evidence"}\n\n')); init?.signal?.addEventListener('abort', () => { stopped = true; controller.error(new DOMException('Aborted', 'AbortError')) }) } })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
    if (url.endsWith('/chats/c2/messages')) return response({ items: stopped ? [message] : [] })
    return response({ items: [] })
  }))
  mount('/papers/p1'); const user = userEvent.setup()
  await screen.findByRole('heading', { name: paper.title }); await user.click(screen.getByRole('tab', { name: 'Questions' })); await user.click(await screen.findByRole('button', { name: 'Stop example' }))
  await user.type(await screen.findByRole('textbox', { name: 'Question about this paper' }), 'What is supported?'); await user.click(screen.getByRole('button', { name: 'Ask question' }))
  expect(await screen.findByText('Partial evidence')).toBeVisible()
  expect(screen.getByText('gpt-5.6-luna · low reasoning')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Stop generation' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Generation stopped')
  await waitFor(() => expect(screen.getByText('interrupted')).toBeVisible())
  expect(screen.getAllByText('Partial evidence')).toHaveLength(1)
  expect(generationRequests).toBe(1)
})

test('Given an oversized PDF, Then upload stays disabled with a recoverable explanation', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ items: [] }))); mount('/library')
  const file = new File(['%PDF'], 'large.pdf', { type: 'application/pdf' }); Object.defineProperty(file, 'size', { value: 26 * 1024 * 1024 })
  await userEvent.setup().upload(screen.getByLabelText('PDF file'), file)
  expect(screen.getByRole('alert')).toHaveTextContent('exceeds 25 MB')
  expect(screen.getByRole('button', { name: 'Upload PDF' })).toBeDisabled()
})

test('Given field provenance, Then readers can see the source of bibliographic metadata', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/papers/p1') ? response({ ...paper, metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } } }) : response({ items: [] })))
  mount('/papers/p1')
  await screen.findByRole('heading', { name: paper.title })
  await userEvent.setup().click(screen.getByText('Metadata sources'))
  expect(screen.getByText('Title: edited by you')).toBeVisible()
  expect(screen.getByText('Authors: OpenAlex')).toBeVisible()
})

test('Given provider metadata, When only the title is edited, Then other fields keep their provider provenance', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/papers/p1') && init?.method === 'PATCH') { const payload: unknown = JSON.parse(String(init.body)); if (typeof payload !== 'object' || payload === null || Object.keys(payload).join(',') !== 'title') return response({ code: 'unexpected_correction', message: 'Only changed fields should be corrected.' }, 422); return response({ ...paper, title: 'Corrected title', metadata_provenance: { title: { source: 'manual' }, authors: { source: 'openalex' } } }) }
    if (url.endsWith('/papers/p1')) return response(paper)
    return response({ items: [] })
  }))
  mount('/papers/p1'); const user = userEvent.setup(); await screen.findByRole('heading', { name: paper.title }); await user.click(screen.getByRole('button', { name: 'Edit' })); const title = screen.getByRole('textbox', { name: 'Title' }); await user.clear(title); await user.type(title, 'Corrected title'); await user.click(screen.getByRole('button', { name: 'Save bibliography' }))
  expect(await screen.findByRole('heading', { name: 'Corrected title' })).toBeVisible()
  await user.click(screen.getByText('Metadata sources')); expect(screen.getByText('Authors: OpenAlex')).toBeVisible()
})

test('Given a stored Luna answer and current Terra selection, Then response metadata shows its stored Luna and low reasoning', async () => {
  const ready = { ...paper, document_status: 'ready', active_document_id: 'd1' }
  const models = ['luna', 'terra'].map((name) => ({ key: `gpt-5.6-${name}`, provider: 'openai', model_id: `gpt-5.6-${name}`, display_name: name === 'luna' ? 'Luna' : 'Terra', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }))
  const answer = { id: 'stored-luna-answer', role: 'assistant', content: 'A saved response from this paper.', state: 'completed', model: 'gpt-5.6-luna', reasoning_effort: 'low', citations: [], created_at: '2026-10-08T00:00:00Z' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/papers/p1')) return response(ready)
    if (url.endsWith('/models')) return response({ items: models })
    if (url.endsWith('/settings')) return response({ default_model: 'gpt-5.6-terra', reasoning_effort: 'high' })
    if (url.endsWith('/papers/p1/chats')) return response({ items: [{ id: 'stored-chat', paper_id: 'p1', document_id: 'd1', title: 'Earlier discussion', created_at: '2026-10-08T00:00:00Z' }] })
    if (url.endsWith('/chats/stored-chat/messages')) return response({ items: [answer] })
    return response({ items: [] })
  }))
  mount('/papers/p1'); const user = userEvent.setup()
  await screen.findByRole('heading', { name: paper.title }); await user.click(screen.getByRole('tab', { name: 'Questions' })); await user.click(await screen.findByRole('button', { name: 'Earlier discussion' }))
  expect(await screen.findByText(answer.content)).toBeVisible()
  expect(screen.getByRole('combobox', { name: 'Model' })).toHaveValue('gpt-5.6-terra')
  expect(screen.getByText('gpt-5.6-luna · low reasoning')).toBeVisible()
  expect(screen.queryByText('gpt-5.6-terra · high reasoning')).not.toBeInTheDocument()
})
