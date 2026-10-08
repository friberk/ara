import { mockApi, noContent } from '@/test/fetch-routes'
import { api, ApiError, apiVoid, downloadUrl, query, remove, safeUrl } from './client'

afterEach(() => vi.unstubAllGlobals())

test('Given query parameters, Then empty values are dropped and the rest are encoded', () => {
  expect(query({ q: 'graph transformers', provider: 'openalex', cursor: null, limit: 20, offset: undefined, filter: '' })).toBe('?q=graph+transformers&provider=openalex&limit=20')
  expect(query({ q: '' })).toBe('')
})

test('Given an API error body, Then ApiError carries its message, status, code and request id', async () => {
  mockApi({ 'GET /papers/p1': () => new Response(JSON.stringify({ code: 'PAPER_NOT_FOUND', message: 'Paper not found.', request_id: 'r1' }), { status: 404 }) })
  await expect(api('/papers/p1')).rejects.toMatchObject({ name: 'ApiError', message: 'Paper not found.', status: 404, code: 'PAPER_NOT_FOUND', requestId: 'r1' })
})

test('Given a network failure, Then the error explains how to recover', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
  const error = await api('/papers').catch((caught: unknown) => caught)
  expect(error).toBeInstanceOf(ApiError)
  expect(error).toMatchObject({ status: 0, message: 'Could not reach the server. Check your connection and try again.' })
})

test('Given a 204 endpoint, Then apiVoid resolves without parsing a body', async () => {
  const { calls } = mockApi({ 'DELETE /chats/c1': () => noContent() })
  await expect(apiVoid('/chats/c1', remove)).resolves.toBeUndefined()
  expect(calls[0]).toMatchObject({ method: 'DELETE', path: '/chats/c1' })
})

test('Given links from providers or models, Then only http(s) URLs are allowed and PDF pages are addressable', () => {
  expect(safeUrl('https://doi.org/10.1/x')).toBe('https://doi.org/10.1/x')
  expect(safeUrl('javascript:alert(1)')).toBeUndefined()
  expect(safeUrl('not a url')).toBeUndefined()
  expect(downloadUrl('d1', 7)).toBe('/api/v1/documents/d1/download#page=7')
})
