import { screen, within } from '@testing-library/react'
import { renderApp } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'

const history = [
  { id: 's1', provider: 'semantic_scholar', query: 'graph transformers', created_at: '2026-10-08T09:00:00Z', last_searched_at: '2026-10-08T11:00:00Z' },
  { id: 's2', provider: 'openalex', query: 'retrieval augmented generation', created_at: '2026-10-08T08:00:00Z', last_searched_at: '2026-10-08T10:00:00Z' },
]
afterEach(() => vi.unstubAllGlobals())

test('Given recent searches, Then the home page offers them beside example topics', async () => {
  mockApi({ 'GET /search-history': { items: history } })
  renderApp('/')
  const suggestions = await screen.findByRole('list', { name: 'Suggestions' })
  const recent = await within(suggestions).findByRole('link', { name: 'Recent search: graph transformers' })
  expect(recent).toHaveAttribute('href', '/search?q=graph+transformers&provider=semantic_scholar')
  expect(within(suggestions).getByRole('link', { name: 'Recent search: retrieval augmented generation' })).toBeVisible()
  expect(within(suggestions).getAllByRole('button', { name: /^Example topic:/ })).toHaveLength(1)
  expect(within(suggestions).getByRole('button', { name: 'Upload a PDF' })).toBeVisible()
})

test('Given search history is unavailable, Then example topics are offered instead', async () => {
  mockApi({ 'GET /search-history': () => json({ code: 'NOT_FOUND', message: 'Not found', request_id: 'r1' }, 404) })
  renderApp('/')
  const suggestions = await screen.findByRole('list', { name: 'Suggestions' })
  expect(within(suggestions).getAllByRole('button', { name: /^Example topic:/ })).toHaveLength(3)
  expect(within(suggestions).queryByRole('link', { name: /^Recent search:/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
