import { z } from 'zod'
const page = z.number().int().positive()
// Fields added by the retrieval overhaul are optional, so answers saved before it still parse (docs/api-contract.md).
const citation = z.object({
  chunk_id: z.string(), document_id: z.string(), page, excerpt: z.string(),
  page_end: page.nullish(), section: z.string().nullish(), kind: z.enum(['front_matter', 'text', 'table', 'references']).nullish(), bboxes: z.array(z.array(z.number())).optional(),
})
const retrieval = z.object({
  mode: z.enum(['hybrid', 'keyword']), profile: z.string().nullish(), reranked: z.boolean().default(false), standalone_query: z.string().nullish(), search_queries: z.array(z.string()).optional(),
  passages_found: z.number().int().default(0), passages_used: z.number().int().default(0), limited_by_context: z.boolean().default(false), note: z.string().nullish(),
  // Relevance-driven evidence (ARA-094); absent on answers saved before it.
  pruned: z.number().int().default(0), evidence_tokens: z.number().int().default(0), summaries_used: z.number().int().default(0), retried: z.boolean().default(false), map_reduce: z.boolean().default(false),
  question_type: z.enum(['lookup', 'broad', 'comparative']).nullish(), sub_questions: z.array(z.string()).optional(),
})
const context = z.object({
  window: z.number().int(), input_tokens: z.number().int(), output_reserved: z.number().int(), summary_version: z.number().int().nullish(),
  recent_turns: z.number().int().default(0), recalled_turns: z.number().int().default(0), truncated: z.boolean().default(false),
})
const completed = z.object({
  id: z.string(), role: z.enum(['user', 'assistant']), content: z.string(), state: z.enum(['completed', 'processing', 'interrupted', 'failed']), model: z.string().nullable(), reasoning_effort: z.string().nullable(), citations: z.array(citation), created_at: z.string(),
  retrieval: retrieval.nullish(), context: context.nullish(), grounding: z.enum(['supported', 'insufficient']).nullish(),
})
// Any stage string is accepted here: the contract has clients ignore stages they do not know.
const status = z.object({ message_id: z.string(), stage: z.string() })
const schemas = { 'message.started': z.object({ message_id: z.string() }), 'message.status': status, 'message.delta': z.object({ text: z.string() }), 'message.completed': completed, 'message.failed': z.object({ code: z.string(), message: z.string(), message_id: z.string().optional() }) }
export type StreamEvent = { [K in keyof typeof schemas]: { event: K; data: z.infer<(typeof schemas)[K]> } }[keyof typeof schemas]
function parseFrame(frame: string): StreamEvent | null {
  let event = ''; const data: string[] = []
  for (const line of frame.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':'); const field = colon < 0 ? line : line.slice(0, colon); const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
    else if (field !== 'id' && field !== 'retry') throw new Error('The response contained an invalid stream field. Reload the conversation.')
  }
  if (!event && !data.length) return null
  if (!(event in schemas) || !data.length) throw new Error('The response contained an unknown stream event. Reload the conversation.')
  const key = event as keyof typeof schemas
  try { return { event: key, data: schemas[key].parse(JSON.parse(data.join('\n'))) } as StreamEvent } catch { throw new Error('The response contained invalid stream data. Reload the conversation.') }
}
export async function readEvents(response: Response, onEvent: (event: StreamEvent) => void): Promise<void> {
  if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) throw new Error('The server did not return a streaming response. Reload the conversation.')
  const reader = response.body.getReader(); const decoder = new TextDecoder('utf-8', { fatal: true }); let buffer = ''; let pendingCR = false
  // Normalize CRLF without losing a CR at a network chunk boundary.
  function append(text: string, final = false) {
    if (pendingCR) { text = `\r${text}`; pendingCR = false }
    if (!final && text.endsWith('\r')) { pendingCR = true; text = text.slice(0, -1) }
    buffer += text.replace(/\r\n?/g, '\n')
    if (buffer.length > 2_000_000) throw new Error('The response stream exceeded the supported frame size.')
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) >= 0) { const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2); const event = parseFrame(frame); if (event) onEvent(event) }
  }
  try {
    while (true) { const { done, value } = await reader.read(); if (done) break; append(decoder.decode(value, { stream: true })) }
    append(decoder.decode(), true)
    if (buffer.trim()) { if (!buffer.split('\n').every((line) => !line.trim() || line.startsWith(':'))) throw new Error('The response stream ended before its last event. Reload the conversation.') }
  } catch (error) { await reader.cancel().catch(() => undefined); throw error } finally { reader.releaseLock() }
}
