import { vi } from 'vitest'

export function json(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
export function noContent() { return new Response(null, { status: 204 }) }

type Handler = (request: { url: URL; method: string; init?: RequestInit; body: unknown }) => Response | Promise<Response>
export type Routes = Record<string, Handler | object>

/**
 * Stubs fetch with "METHOD /path" routes (path without the /api/v1 prefix or query string).
 * Paths may end with * to match a prefix. Unmatched requests get an empty collection, like an empty database.
 */
export function mockApi(routes: Routes) {
  const calls: { method: string; path: string; url: URL; body: unknown }[] = []
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
    return json({ items: [] })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}
