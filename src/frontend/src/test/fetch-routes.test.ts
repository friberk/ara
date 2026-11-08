// The test API double itself: a request nobody declared has to fail the test that made it.
import { mockApi, takeUnexpectedRequests } from './fetch-routes'

afterEach(() => vi.unstubAllGlobals())

const get = async (path: string) => {
  const response = await fetch(`/api/v1${path}`)
  return { status: response.status, body: await response.json() as Record<string, unknown> }
}

test('Given a request no test declared, Then it is recorded for the afterEach check and answers 500', async () => {
  mockApi({})
  const answer = await get('/papers/p1/nothing-here')
  expect(answer.status).toBe(500)
  expect(takeUnexpectedRequests()).toEqual([{ method: 'GET', path: '/papers/p1/nothing-here' }])
  expect(takeUnexpectedRequests()).toEqual([])
})

test('Given a write nobody declared on a background path, Then it is still undeclared', async () => {
  mockApi({})
  await fetch('/api/v1/papers', { method: 'POST', body: '{}' })
  expect(takeUnexpectedRequests()).toEqual([{ method: 'POST', path: '/papers' }])
})

test('Given a declared route, Then it wins over the background answer', async () => {
  mockApi({ 'GET /features': { open_models: true } })
  expect((await get('/features')).body).toEqual({ open_models: true })
  expect(takeUnexpectedRequests()).toEqual([])
})

test.each([
  ['/features', { open_models: false }],
  ['/settings', { default_model: 'gpt-5.6-luna', reasoning_effort: 'low' }],
  ['/models', { items: [] }],
  ['/papers', { items: [] }],
  ['/chats', { items: [] }],
  ['/jobs', { items: [] }],
  ['/search-history', { items: [] }],
  ['/uploads/matches', { items: [] }],
  ['/chats/c1/memory', { memory: null, total_messages: 0 }],
  ['/papers/p1/summaries', { items: [], blocked: null }],
])('Given the background route %s, Then it answers in the real shape', async (path, expected) => {
  mockApi({})
  const answer = await get(path)
  expect(answer).toEqual({ status: 200, body: expected })
  expect(takeUnexpectedRequests()).toEqual([])
})

test('Given single-object background routes, Then they name what was asked for and are not lists', async () => {
  mockApi({})
  const usage = (await get('/chats/c1/usage')).body
  expect(Object.keys(usage).sort()).toEqual(['context', 'cost'])
  const status = (await get('/papers/p7/fulltext')).body
  expect(status).toMatchObject({ paper_id: 'p7', api_key_configured: false, retrieval_job: null })
  const document = (await get('/documents/d9')).body
  expect(document).toMatchObject({ id: 'd9', status: 'ready' })
  expect(document).not.toHaveProperty('items')
  expect(takeUnexpectedRequests()).toEqual([])
})

test('Given a nested path under a background route, Then it is not treated as background', async () => {
  mockApi({})
  await get('/documents/d9/chunks/c1')
  await get('/chats/c1')
  await get('/chats/c1/messages')
  await get('/papers/p1')
  expect(takeUnexpectedRequests().map((request) => request.path)).toEqual(['/documents/d9/chunks/c1', '/chats/c1', '/chats/c1/messages', '/papers/p1'])
})
