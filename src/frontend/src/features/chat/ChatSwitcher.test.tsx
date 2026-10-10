// ARA-104: the pane's top row. Title on the left (its menu holds only Rename and Delete), then Chat history and New conversation.
import { screen, waitFor, within } from '@testing-library/react'
import { json, mockApi } from '@/test/fetch-routes'
import { chatRow, included, mount, paper, settings } from './pane-test-kit'

afterEach(() => vi.useRealTimers())

const openHistory = async (user: ReturnType<typeof mount>['user']) => {
  await user.click(await screen.findByRole('button', { name: 'Chat history' }))
  return screen.findByRole('dialog', { name: 'Chat history for this paper' })
}

test('Given a saved chat, Then the top row has the title, Chat history and New conversation, and no verbose label', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { title: 'Research question' })] } })
  const { user } = mount('/papers/p1/chats/c1')
  const row = (await screen.findByRole('button', { name: 'Research question' })).parentElement as HTMLElement
  expect(within(row).getByRole('button', { name: 'Chat history' })).toBeVisible()
  expect(within(row).getByRole('button', { name: 'New conversation' })).toBeVisible()
  const history = await openHistory(user)
  expect(screen.queryByText(/Conversations about this paper/)).not.toBeInTheDocument()
  expect(history).toBeVisible()
})

test('Given a saved chat, When its title is pressed, Then the menu offers only Rename and Delete', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { title: 'Research question' })] } })
  const { user } = mount('/papers/p1/chats/c1')
  await user.click(await screen.findByRole('button', { name: 'Research question' }))
  const menu = await screen.findByRole('menu')
  expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Rename', 'Delete'])
})

test('Given a new unsaved conversation, Then its title is plain text with no menu', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1')] } })
  mount('/papers/p1')
  expect(await screen.findByText('New conversation', { selector: 'span' })).toBeVisible()
  expect(screen.getAllByRole('button', { name: 'New conversation' })).toHaveLength(1)
  expect(screen.queryByRole('button', { expanded: false, name: /New conversation/ })).toBe(null)
})

test('Given chats of different ages, When Chat history opens, Then rows run newest first with compact relative times and exact titles', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-08T15:00:00Z'))
  mockApi({
    ...settings,
    'GET /chats': { items: [
      chatRow('c1', { title: 'Just now chat', last_activity_at: '2026-10-08T14:59:40Z' }),
      chatRow('c2', { title: 'Hours chat', last_activity_at: '2026-10-08T12:00:00Z' }),
      chatRow('c3', { title: 'Days chat', last_activity_at: '2026-10-05T12:00:00Z' }),
      chatRow('c4', { title: 'Old chat', last_activity_at: '2025-06-30T12:00:00Z' }),
    ] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const history = await openHistory(user)
  const rows = await within(history).findAllByRole('option')
  expect(rows.map((row) => row.querySelector('time [aria-hidden]')?.textContent)).toEqual(['now', '3h', '3d', 'Jun 30, 2025'])
  const hours = rows[1]!.querySelector('time')!
  expect(hours).toHaveAttribute('dateTime', '2026-10-08T12:00:00Z')
  expect(hours).toHaveAttribute('title', expect.stringMatching(/October 8, 2026/))
  expect(within(hours).getByText('3 hours ago')).toHaveClass('sr-only')
  expect(hours).not.toHaveTextContent('12m')
})

test('Given several chats, Then the open one is marked and an earlier PDF keeps its badge', async () => {
  mockApi({
    ...settings,
    'GET /chats': { items: [chatRow('c1', { title: 'Research question', last_question_preview: 'What was measured?' }), chatRow('c2', { title: 'Older discussion', papers: [included(paper, { document_id: 'd0' })] })] },
  })
  const { user } = mount('/papers/p1/chats/c1')
  const history = await openHistory(user)
  expect(within(history).getByRole('option', { name: /Research question/ })).toHaveAttribute('aria-current', 'true')
  expect(within(history).getByRole('option', { name: /Older discussion/ })).not.toHaveAttribute('aria-current')
  expect(within(history).getByRole('option', { name: /Older discussion/ })).toHaveTextContent('Earlier PDF')
  expect(within(history).getByRole('option', { name: /Research question/ })).toHaveTextContent('What was measured?')
})

test('Given the history, When a row is chosen, Then its chat opens and the popover closes', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { title: 'First chat' }), chatRow('c2', { title: 'Second chat' })] } })
  const { user } = mount('/papers/p1/chats/c1')
  const history = await openHistory(user)
  await user.click(within(history).getByRole('option', { name: /Second chat/ }))
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c2'))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Chat history for this paper' })).not.toBeInTheDocument())
})

test('Given the history, When arrow keys and Enter are used, Then the keyboard opens a chat and focus returns to Chat history on Escape', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { title: 'First chat' }), chatRow('c2', { title: 'Second chat' })] } })
  const { user } = mount('/papers/p1/chats/c1')
  await openHistory(user)
  await user.keyboard('{ArrowDown}{Enter}')
  await waitFor(() => expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p1/chats/c2'))
  await user.click(screen.getByRole('button', { name: 'Chat history' }))
  await screen.findByRole('dialog', { name: 'Chat history for this paper' })
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chat history' })).toHaveFocus())
})

test('Given no chats, Then the history says "No chats yet"', async () => {
  mockApi(settings)
  const { user } = mount('/papers/p1')
  expect(await within(await openHistory(user)).findByText('No chats yet')).toBeVisible()
})

test('Given the chat list fails, Then the history offers a retry', async () => {
  let failures = 0
  mockApi({ ...settings, 'GET /chats': () => (failures++ < 1 ? json({ code: 'UNAVAILABLE', message: 'down' }, 503) : json({ items: [chatRow('c9', { title: 'Back chat' })] })) })
  const { user } = mount('/papers/p1')
  const history = await openHistory(user)
  await user.click(await within(history).findByRole('button', { name: 'Try again' }))
  expect(await within(history).findByRole('option', { name: /Back chat/ })).toBeVisible()
})

test('Given 7 chats, Then there is no filter; given 8, the filter narrows by title', async () => {
  const many = (count: number) => Array.from({ length: count }, (_, index) => chatRow(`c${index + 1}`, { title: index === 7 ? 'Unique ablation' : `Chat number ${index + 1}` }))
  mockApi({ ...settings, 'GET /chats': { items: many(7) } })
  const first = mount('/papers/p1')
  expect(within(await openHistory(first.user)).queryByPlaceholderText('Filter chats')).not.toBeInTheDocument()
})

test('Given 8 chats, When the filter is typed, Then only matching chats remain', async () => {
  const items = Array.from({ length: 8 }, (_, index) => chatRow(`c${index + 1}`, { title: index === 7 ? 'Unique ablation' : `Chat number ${index + 1}` }))
  mockApi({ ...settings, 'GET /chats': { items } })
  const { user } = mount('/papers/p1')
  const history = await openHistory(user)
  await user.type(within(history).getByPlaceholderText('Filter chats'), 'ablation')
  expect(within(history).getAllByRole('option')).toHaveLength(1)
  expect(within(history).getByRole('option')).toHaveTextContent('Unique ablation')
})
