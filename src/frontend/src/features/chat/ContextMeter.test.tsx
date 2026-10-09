// The context and cost ring in the composer (ARA-085).
import { screen, waitFor, within } from '@testing-library/react'
import type { ChatUsage } from '@/api/types'
import { json, mockApi, type Routes } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ContextMeter } from './ContextMeter'

afterEach(() => vi.unstubAllGlobals())

const zero = '0.00000000'
const empty: ChatUsage = {
  context: { used_tokens: null, input_budget: 64_000, window: 1_050_000, model: 'gpt-5.6-luna' },
  cost: { total: zero, answers: zero, planning: zero, compaction: zero, embeddings: zero, reranking: zero, local: false, unrecorded_turns: 0 },
}
const used: ChatUsage = {
  context: { ...empty.context, used_tokens: 12_400 },
  cost: { total: '0.01230000', answers: '0.00900000', planning: '0.00100000', compaction: '0.00200000', embeddings: '0.00010000', reranking: '0.00020000', local: false, unrecorded_turns: 0 },
}
const luna = { model: 'gpt-5.6-luna', reasoning_effort: 'low' }

function mount(usage: Routes[string], settings = luna) {
  const api = mockApi({ 'GET /chats/c1/usage': usage })
  const view = renderWithProviders(<TooltipProvider><ContextMeter chatId="c1" settings={settings} /></TooltipProvider>)
  const rerender = (next: typeof luna) => view.rerender(<TooltipProvider><ContextMeter chatId="c1" settings={next} /></TooltipProvider>)
  return { ...api, ...view, rerender }
}

test('Given a chat with no turns, Then the ring is empty and the name says $0.00', async () => {
  mount(empty)
  const ring = await screen.findByRole('button', { name: 'Context 0% used of 64k tokens. $0.00 this chat.' })
  expect(ring.querySelector('[data-fraction]')).toHaveAttribute('data-fraction', '0')
})

test('Given a completed turn, When the ring is hovered, Then used and total tokens, percent and cost show', async () => {
  const { user } = mount(used)
  const ring = await screen.findByRole('button', { name: 'Context 19% used of 64k tokens. $0.0123 this chat.' })
  expect(ring.querySelector('[data-fraction]')).toHaveAttribute('data-fraction', String(12_400 / 64_000))
  await user.hover(ring)
  const card = await screen.findByRole('dialog', { name: 'Context and cost' })
  expect(within(card).getByText('12.4k / 64k tokens · 19%')).toBeVisible()
  expect(within(card).getByText('$0.0123 this chat')).toBeVisible()
  expect(within(card).getByText('Model window 1.05M tokens')).toBeVisible()
  for (const [label, value] of [['Answers', '$0.0090'], ['Follow-up planning', '$0.0010'], ['Conversation summaries', '$0.0020'], ['Query embeddings', '$0.0001'], ['Reranking', '$0.0002']] as const) {
    expect(within(card).getByText(label).parentElement).toHaveTextContent(value)
  }
})

test('Given a free breakdown line, Then it is left out; a model whose window equals its budget shows no window line', async () => {
  const { user } = mount({ ...used, context: { ...used.context, window: 64_000 }, cost: { ...used.cost, planning: zero, reranking: zero } })
  await user.hover(await screen.findByRole('button', { name: /^Context 19%/ }))
  const card = await screen.findByRole('dialog', { name: 'Context and cost' })
  expect(within(card).queryByText('Follow-up planning')).not.toBeInTheDocument()
  expect(within(card).queryByText('Reranking')).not.toBeInTheDocument()
  expect(within(card).queryByText(/Model window/)).not.toBeInTheDocument()
})

test('Given a local model, Then the card says so and shows $0.00', async () => {
  const { user } = mount({ context: { used_tokens: 1_900, input_budget: 3_072, window: 8_192, model: 'ifm' }, cost: { ...empty.cost, local: true } }, { model: 'ifm', reasoning_effort: 'default' })
  await user.hover(await screen.findByRole('button', { name: 'Context 62% used of 3.1k tokens. Local model, $0.00.' }))
  const card = await screen.findByRole('dialog', { name: 'Context and cost' })
  expect(within(card).getByText('Local model · $0.00')).toBeVisible()
  expect(within(card).getByText('Model window 8.2k tokens')).toBeVisible()
})

test('Given earlier answers from before costs were recorded, Then the card says they are not counted', async () => {
  const { user } = mount({ ...used, cost: { ...used.cost, unrecorded_turns: 2 } })
  await user.hover(await screen.findByRole('button', { name: /^Context/ }))
  expect(await screen.findByText('2 earlier answers were not tracked.')).toBeVisible()
})

test('Given keyboard focus, Then the card opens, and Escape closes it without losing focus', async () => {
  const { user } = mount(used)
  const ring = await screen.findByRole('button', { name: /^Context/ })
  await user.tab()
  expect(ring).toHaveFocus()
  expect(await screen.findByRole('dialog', { name: 'Context and cost' })).toBeVisible()
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(ring).toHaveFocus()
})

test('Given a tap or click, Then the card toggles and stays open without hover', async () => {
  const { user } = mount(used)
  const ring = await screen.findByRole('button', { name: /^Context/ })
  await user.click(ring)
  expect(await screen.findByRole('dialog', { name: 'Context and cost' })).toBeVisible()
  await user.unhover(ring)
  expect(screen.getByRole('dialog', { name: 'Context and cost' })).toBeVisible()
  await user.click(ring)
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

test('Given the model switches, Then the usage is requested for the new model and the total follows', async () => {
  const { calls, rerender, user } = mount(({ url }) => json(url.searchParams.get('model') === 'ifm' ? { ...used, context: { used_tokens: 12_400, input_budget: 3_072, window: 8_192, model: 'ifm' } } : used))
  await screen.findByRole('button', { name: 'Context 19% used of 64k tokens. $0.0123 this chat.' })
  expect(calls[0]?.url.searchParams.get('model')).toBe('gpt-5.6-luna')
  expect(calls[0]?.url.searchParams.get('reasoning_effort')).toBe('low')
  rerender({ model: 'ifm', reasoning_effort: 'default' })
  const ring = await screen.findByRole('button', { name: 'Context 404% used of 3.1k tokens. $0.0123 this chat.' })
  expect(ring.querySelector('[data-fraction]')).toHaveAttribute('data-fraction', '1')
  await user.hover(ring)
  expect(await screen.findByText('12.4k / 3.1k tokens · 404%')).toBeVisible()
  expect(calls.filter((call) => call.path === '/chats/c1/usage').map((call) => call.url.searchParams.get('model'))).toEqual(['gpt-5.6-luna', 'ifm'])
})

test('Given a server that cannot report usage, Then no ring shows and nothing alerts', async () => {
  mount(() => json({ code: 'NOT_FOUND', message: 'Not Found' }, 404))
  await waitFor(() => expect(screen.queryByRole('button', { name: /^Context/ })).not.toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
