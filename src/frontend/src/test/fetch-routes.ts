import { act } from '@testing-library/react'
import { vi } from 'vitest'
import type { components } from '@/api/generated'
import type { ChatMemoryState, ChatUsage, DocumentDetail, Features, FullTextStatus, SummaryPage } from '@/api/types'

export function json(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
export function noContent() { return new Response(null, { status: 204 }) }

type Handler = (request: { url: URL; method: string; init?: RequestInit; body: unknown }) => Response | Promise<Response>
export type Routes = Record<string, Handler | object>

/** Declares that these chats have no saved messages yet. */
export const noHistory = (...chatIds: string[]): Routes => Object.fromEntries(chatIds.map((id) => [`GET /chats/${id}/messages`, { items: [] }]))
/** Declares that these papers have no summaries yet. */
export const noSummaries = (...paperIds: string[]): Routes => Object.fromEntries(paperIds.map((id) => [`GET /papers/${id}/summaries`, { items: [], blocked: null }]))

/** A route that stays open until `respond()`, so a test can cancel first and have the server answer afterwards. */
export function heldResponse(answer: () => Response) {
  let signal: AbortSignal | null | undefined
  let release = () => {}
  const handler: Handler = ({ init }) => { signal = init?.signal; return new Promise<Response>((resolve) => { release = () => resolve(answer()) }) }
  return {
    handler,
    aborted: () => signal?.aborted,
    /** Answers, then gives the late response time to reach whatever would act on it. */
    respond: () => act(async () => { release(); await new Promise((resolve) => setTimeout(resolve, 30)) }),
  }
}

const CREATED_AT = '2026-01-01T00:00:00Z'
const emptyDocument = (id: string): DocumentDetail => ({ id, paper_id: 'unset-paper', file_name: 'paper.pdf', page_count: null, byte_size: 0, status: 'ready', acquisition: null, created_at: CREATED_AT })
const emptyUsage: ChatUsage = {
  context: { used_tokens: null, input_budget: 0, window: 0, model: 'gpt-5.6-luna' },
  cost: { total: '0', answers: '0', planning: '0', compaction: '0', embeddings: '0', reranking: '0', local: false, unrecorded_turns: 0 },
}

/**
 * What the app asks for on every page, or whenever a reader or conversation opens, in the real API's shapes. A test
 * that depends on one of these answers, even an empty list, declares it instead of leaning on the default.
 */
const backgroundRoutes: { method: string; pattern: RegExp; answer: (id: string) => object }[] = [
  { method: 'GET', pattern: /^\/features$/, answer: () => ({ open_models: false }) satisfies Features },
  { method: 'GET', pattern: /^\/settings$/, answer: () => ({ default_model: 'gpt-5.6-luna', reasoning_effort: 'low' }) satisfies components['schemas']['Defaults'] },
  { method: 'GET', pattern: /^\/(models|papers|chats|jobs|search-history|uploads\/matches)$/, answer: () => ({ items: [] }) },
  { method: 'GET', pattern: /^\/chats\/([^/]+)\/usage$/, answer: () => emptyUsage },
  { method: 'GET', pattern: /^\/chats\/([^/]+)\/memory$/, answer: () => ({ memory: null, total_messages: 0 }) satisfies ChatMemoryState },
  { method: 'GET', pattern: /^\/papers\/([^/]+)\/summaries$/, answer: () => ({ items: [], blocked: null }) satisfies SummaryPage },
  { method: 'GET', pattern: /^\/papers\/([^/]+)\/fulltext$/, answer: (id) => ({ paper_id: id, api_key_configured: false, retrieval_job: null, document_id: null, ingest_job_id: null, acquisition: null }) satisfies FullTextStatus },
  { method: 'GET', pattern: /^\/documents\/([^/]+)$/, answer: emptyDocument },
]

function backgroundAnswer(method: string, path: string) {
  for (const route of backgroundRoutes) {
    const match = route.method === method ? route.pattern.exec(path) : null
    if (match) return route.answer(match[1] ?? '')
  }
  return null
}

type Unexpected = { method: string; path: string }
let openLogs: Unexpected[][] = []

/** The undeclared requests of the current test; reading them clears them. */
export function takeUnexpectedRequests(): Unexpected[] {
  const found = openLogs.flat()
  openLogs = []
  return found
}

/** Runs after every test (see setup.ts): a request nobody declared fails the test that made it. */
export function failOnUnexpectedRequests() {
  const found = takeUnexpectedRequests()
  if (found.length) throw new Error(`Undeclared API request(s). Declare each in this test's mockApi routes:\n${found.map(({ method, path }) => `  ${method} ${path}`).join('\n')}`)
}

/**
 * Stubs fetch with "METHOD /path" routes (path without the /api/v1 prefix or query string).
 * Paths may end with * to match a prefix. Declared routes win, then the background routes above; any other request
 * fails its test. It also gets a 500, because an error answer alone would rarely fail anything.
 */
export function mockApi(routes: Routes) {
  const calls: { method: string; path: string; url: URL; body: unknown }[] = []
  const unexpected: Unexpected[] = []
  openLogs.push(unexpected)
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.pathname.replace(/^\/api\/v1/, '')
    let body: unknown = init?.body
    if (typeof init?.body === 'string') { try { body = JSON.parse(init.body) } catch { body = init.body } }
    calls.push({ method, path, url, body })
    for (const [key, handler] of Object.entries(routes)) {
      const [routeMethod, routePath = ''] = key.split(' ')
      const matches = routeMethod === method && (routePath.endsWith('*') ? path.startsWith(routePath.slice(0, -1)) : path === routePath)
      if (matches) return typeof handler === 'function' ? (handler as Handler)({ url, method, init, body }) : json(handler)
    }
    const background = backgroundAnswer(method, path)
    if (background) return json(background)
    unexpected.push({ method, path })
    return json({ code: 'UNDECLARED_TEST_REQUEST', message: `${method} ${path} was not declared by this test.` }, 500)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}
