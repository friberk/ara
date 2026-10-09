// Opening a chat restores the model and effort of its latest answer (ARA-083).
import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, luna, mount, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const terra = { ...luna, key: 'gpt-5.6-terra', model_id: 'gpt-5.6-terra', display_name: 'Terra', reasoning_efforts: ['low', 'medium', 'high'] }
const saved = { 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } }
const history = (model: string, effort: string) => json({ items: [userMessage('u1', 'Why?'), assistantMessage('a1', 'Because.', { model, reasoning_effort: effort })] })

test('Given a chat answered by Terra at high, When it opens, Then the composer selects Terra and high without saving a default', async () => {
  const { calls } = mockApi({ ...saved, 'GET /models': { items: [luna, terra] }, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': () => history(terra.key, 'high') })
  mount('/papers/p1/chats/c1')
  await screen.findByText('Because.')
  await waitFor(() => expect(screen.getByRole('button', { name: /Terra/ })).toBeVisible())
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('Given a chat answered by a model that is gone, When it opens, Then the current selection stays and history is unchanged', async () => {
  const { calls } = mockApi({ ...saved, 'GET /models': { items: [luna] }, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': () => history('retired-model', 'high') })
  mount('/papers/p1/chats/c1')
  await screen.findByText('Because.')
  expect(screen.getByRole('button', { name: /Luna/ })).toBeVisible()
  expect(calls.some((call) => call.method !== 'GET')).toBe(false)
})

test('Given an unavailable model answered the chat, When it opens, Then the current selection stays', async () => {
  mockApi({ ...saved, 'GET /models': { items: [luna, { ...terra, status: 'unavailable' }] }, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': () => history(terra.key, 'high') })
  mount('/papers/p1/chats/c1')
  await screen.findByText('Because.')
  expect(screen.getByRole('button', { name: /Luna/ })).toBeVisible()
})

test('Given a chat restored to Terra, When the paper summary is generated, Then the request names Terra and its effort', async () => {
  const { calls, user } = (() => {
    const api = mockApi({ ...saved, 'GET /models': { items: [luna, terra] }, 'GET /chats': { items: [chatRow('c1')] }, 'GET /chats/c1/messages': () => history(terra.key, 'high'), 'GET /papers/p1/summaries': { items: [] }, 'POST /papers/p1/summaries': { job_id: 'j1', summary_id: null }, 'GET /jobs/j1': () => new Promise<Response>(() => {}) })
    return { calls: api.calls, ...mount('/papers/p1/chats/c1') }
  })()
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  await screen.findByText('Because.')
  await waitFor(() => expect(screen.getByRole('button', { name: /Terra/ })).toBeVisible())
  await user.click(await within(card).findByRole('button', { name: 'Generate summary' }))
  await waitFor(() => expect(calls.find((call) => call.method === 'POST' && call.path === '/papers/p1/summaries')?.body).toMatchObject({ model: terra.key, reasoning_effort: 'high' }))
})
