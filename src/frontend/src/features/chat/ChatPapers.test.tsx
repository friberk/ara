// The paper row outside a workspace (ARA-110): a pill opens the paper's page instead of a reader tab.
import { act, screen, within } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { CurrentPath } from './pane-test-routes'
import { ChatPapers } from './ChatPapers'
import type { Paper } from '@/api/types'
import { included, paper, paper2 } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

test('Given no workspace reader, When a pill is clicked, Then the paper opens on its own page', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /papers/p2': paper2 })
  const { user } = renderWithProviders(<TooltipProvider><ChatPapers papers={[included(paper), included(paper2)]} onRemove={vi.fn()} /><CurrentPath /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Dense passage retrieval' }))
  expect(screen.getByLabelText('Current path')).toHaveTextContent('/papers/p2')
})

test('Given a single paper, Then nothing renders', () => {
  mockApi({})
  renderWithProviders(<TooltipProvider><ChatPapers papers={[included(paper)]} onRemove={vi.fn()} /></TooltipProvider>)
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

describe('the row is one line (ARA-110)', () => {
  const rowName = 'Papers in this conversation'
  const five: Paper[] = Array.from({ length: 5 }, (_, n) => ({ ...paper2, id: `f${n}`, title: `Study number ${n}`, active_document_id: `fd${n}` }))
  let rowWidth = 0
  let observed: (() => void)[] = []
  const originalObserver = window.ResizeObserver

  beforeEach(() => {
    rowWidth = 0
    observed = []
    // jsdom has no layout: each pill is 150px, the +N pill 30px, and the row is as wide as the test says.
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.hasAttribute('data-paper-id') ? 150 : this.hasAttribute('data-more') ? 30 : 0
    })
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.getAttribute('aria-label') === rowName ? rowWidth : 0
    })
    window.ResizeObserver = class { constructor(callback: () => void) { observed.push(callback) } observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
  })
  afterEach(() => { vi.restoreAllMocks(); window.ResizeObserver = originalObserver })

  const mountRow = () => {
    mockApi({})
    return renderWithProviders(<TooltipProvider><ChatPapers papers={five.map((item) => included(item))} onRemove={vi.fn()} /></TooltipProvider>)
  }

  test('Given a narrow row, Then it shows the pills that fit on one line and a +N pill counting the rest', () => {
    rowWidth = 432
    mountRow()
    const row = screen.getByRole('list', { name: rowName })
    expect(within(row).getAllByRole('button', { name: /^Study number/ })).toHaveLength(2)
    expect(within(row).getByRole('button', { name: '+3 more papers' })).toBeVisible()
    expect(within(row).getAllByRole('button', { name: /^Study number/ }).map((button) => button.getAttribute('aria-label'))).toEqual(['Study number 0', 'Study number 1'])
  })

  test('Given a wide row, Then every pill shows and there is no +N pill', () => {
    rowWidth = 1032
    mountRow()
    expect(within(screen.getByRole('list', { name: rowName })).getAllByRole('button', { name: /^Study number/ })).toHaveLength(5)
    expect(screen.queryByRole('button', { name: /more papers/ })).not.toBeInTheDocument()
  })

  test('Given the row is resized, Then the count follows its width', () => {
    rowWidth = 432
    mountRow()
    expect(screen.getByRole('button', { name: '+3 more papers' })).toBeVisible()
    rowWidth = 632
    act(() => observed.forEach((callback) => callback()))
    expect(screen.getByRole('button', { name: '+2 more papers' })).toBeVisible()
  })

  test('Given a row too narrow for any pill, Then one pill still shows', () => {
    rowWidth = 100
    mountRow()
    expect(within(screen.getByRole('list', { name: rowName })).getAllByRole('button', { name: /^Study number/ })).toHaveLength(1)
    expect(screen.getByRole('button', { name: '+4 more papers' })).toBeVisible()
  })

  test('Given row pills, Then their titles are cut shorter than the composer pills', () => {
    rowWidth = 432
    mountRow()
    const label = within(screen.getByRole('button', { name: 'Study number 0' })).getByText('Study number 0')
    expect(label).toHaveStyle({ maxWidth: '16ch' })
  })
})
