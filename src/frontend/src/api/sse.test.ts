import { readEvents } from './sse'

function fragmented(text: string) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream<Uint8Array>({ start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })
}

test('Given fragmented UTF-8 and multiple frames, When read, Then every event retains its data', async () => {
  const events: { event: string; data: unknown }[] = []
  await readEvents(fragmented(': keepalive\r\n\r\nevent: message.started\r\ndata: {"message_id":"a"}\r\n\r\nevent: message.delta\ndata: {"text":"café 🔬"}\n\nevent: message.failed\ndata: {"code":"provider_error","message":"Try again"}\n\n'), (event) => events.push(event))
  expect(events).toEqual([{ event: 'message.started', data: { message_id: 'a' } }, { event: 'message.delta', data: { text: 'café 🔬' } }, { event: 'message.failed', data: { code: 'provider_error', message: 'Try again' } }])
})

test.each(['event: surprise\ndata: {}\n\n', 'event: message.delta\ndata: nope\n\n', 'event: message.delta\ndata: {"text":3}\n\n', 'event: message.delta\ndata: {"text":"unfinished"}'])('Given invalid SSE, Then a visible-error-ready exception is raised: %s', async (frame) => {
  await expect(readEvents(fragmented(frame), () => undefined)).rejects.toThrow()
})

test('Given a final heartbeat followed by an incomplete event, Then framing failure is reported', async () => {
  await expect(readEvents(fragmented(': keepalive\nevent: message.delta\ndata: {"text":"lost"}'), () => undefined)).rejects.toThrow('ended')
})

// Retrieval and conversation context (ARA-078, docs/api-contract.md "Retrieval and conversation context").
const completedMessage = {
  id: 'm1', role: 'assistant', content: 'Recall rose.', state: 'completed', model: 'gpt-5.6-luna', reasoning_effort: 'low', created_at: '2026-10-09T12:00:00Z',
  citations: [{ chunk_id: '12345678-1234-1234-1234-123456789abc', document_id: 'd1', page: 5, page_end: 6, section: 'Results > Open-domain QA', kind: 'table', bboxes: [[5, 10, 20, 300, 40]], excerpt: 'BM25 recall 71.2' }],
  retrieval: { mode: 'hybrid', profile: 'openai-3-large', reranked: false, standalone_query: 'What recall did BM25 reach?', search_queries: ['BM25 recall'], passages_found: 12, passages_used: 6, limited_by_context: true, note: null },
  context: { window: 8192, input_tokens: 5120, output_reserved: 2048, summary_version: 2, recent_turns: 4, recalled_turns: 1, truncated: false },
  grounding: 'insufficient',
}

test('Given status events with known and unknown stages, When read, Then each passes through for the client to show or ignore', async () => {
  const events: { event: string; data: unknown }[] = []
  await readEvents(fragmented('event: message.status\ndata: {"message_id":"m1","stage":"retrieving"}\n\nevent: message.status\ndata: {"message_id":"m1","stage":"daydreaming"}\n\n'), (event) => events.push(event))
  expect(events).toEqual([{ event: 'message.status', data: { message_id: 'm1', stage: 'retrieving' } }, { event: 'message.status', data: { message_id: 'm1', stage: 'daydreaming' } }])
})

test('Given a completed answer with retrieval, context, grounding and passage provenance, When read, Then none of it is dropped', async () => {
  const events: { event: string; data: unknown }[] = []
  await readEvents(fragmented(`event: message.completed\ndata: ${JSON.stringify(completedMessage)}\n\n`), (event) => events.push(event))
  expect(events).toEqual([{ event: 'message.completed', data: completedMessage }])
})

test('Given a completed answer saved before retrieval details existed, When read, Then it still parses', async () => {
  const legacy = { ...completedMessage, retrieval: undefined, context: undefined, grounding: undefined }
  const events: { event: string; data: unknown }[] = []
  await readEvents(fragmented(`event: message.completed\ndata: ${JSON.stringify({ ...legacy, citations: [{ chunk_id: 'c', document_id: 'd1', page: 2, excerpt: 'Old' }] })}\n\n`), (event) => events.push(event))
  expect(events).toHaveLength(1)
})
