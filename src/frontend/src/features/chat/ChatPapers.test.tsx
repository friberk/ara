// The paper row outside a workspace (ARA-110): a pill opens the paper's page instead of a reader tab.
import { screen } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { CurrentPath } from './pane-test-routes'
import { ChatPapers } from './ChatPapers'
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
