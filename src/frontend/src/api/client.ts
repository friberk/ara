const prefix = '/api/v1'
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string, readonly requestId?: string) { super(message); this.name = 'ApiError' }
}
export async function checkedResponse(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try { response = await fetch(`${prefix}${path}`, init) } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('Could not reach the server. Check your connection and try again.', 0)
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const fields = typeof body === 'object' && body !== null ? body as Record<string, unknown> : {}
    throw new ApiError(typeof fields.message === 'string' ? fields.message : `Request failed (${response.status}). Try again.`, response.status, typeof fields.code === 'string' ? fields.code : undefined, typeof fields.request_id === 'string' ? fields.request_id : undefined)
  }
  return response
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> { return (await checkedResponse(path, init)).json() as Promise<T> }
/** For endpoints that answer 204 No Content. */
export async function apiVoid(path: string, init?: RequestInit): Promise<void> { await checkedResponse(path, init) }
export function json(method: 'POST' | 'PATCH' | 'PUT', body: unknown): RequestInit { return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } }
export const remove: RequestInit = { method: 'DELETE' }
export function query(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined && value !== '') search.set(key, String(value))
  const text = search.toString()
  return text ? `?${text}` : ''
}
export function downloadUrl(documentId: string, page?: number) { return `${prefix}/documents/${encodeURIComponent(documentId)}/download${page ? `#page=${page}` : ''}` }
export function safeUrl(value: string | null | undefined): string | undefined { if (!value) return undefined; try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined } }
