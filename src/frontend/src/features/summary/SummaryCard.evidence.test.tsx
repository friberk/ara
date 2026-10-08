// Evidence jump from a summary (ui-evidence): kept apart from SummaryCard.test.tsx so the two can change independently.
import { screen, within } from '@testing-library/react'
import type { Citation, Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { WorkspaceContext, type WorkspaceContextValue } from '@/features/workspace/workspace-context'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { SummaryCard } from '.'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const citation: Citation = { chunk_id: '12345678-1234-4234-8234-123456789abc', document_id: 'd1', page: 4, excerpt: 'The experiment uses the Orion-12 dataset.' }
const content = `The study evaluates on Orion-12. [source:${citation.chunk_id}]`
afterEach(() => vi.unstubAllGlobals())

test('Given a cited summary in the workspace, When a source chip is opened, Then the reader is sent the summary text as its claim', async () => {
  mockApi({
    'GET /models': { items: [luna] },
    'GET /settings': { default_model: luna.key, reasoning_effort: 'low' },
    'GET /papers/p1/summaries': { items: [{ id: 's1', paper_id: 'p1', document_id: 'd1', model: luna.key, reasoning_effort: 'low', content, citations: [citation], created_at: '2026-10-08T12:01:00Z' }] },
  })
  const workspace = { showSource: vi.fn() } as unknown as WorkspaceContextValue
  const { user } = renderWithProviders(
    <WorkspaceContext.Provider value={workspace}>
      <TooltipProvider><GenerationSettingsProvider><SummaryCard paper={paper} /></GenerationSettingsProvider></TooltipProvider>
    </WorkspaceContext.Provider>,
  )
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  await user.click(await within(card).findByRole('button', { name: 'Show full summary' }))
  await user.click(within(within(card).getByRole('group', { name: 'Sources' })).getByRole('button', { name: 'Source, page 4' }))
  expect(workspace.showSource).toHaveBeenCalledWith(citation, 'The study evaluates on Orion-12.')
})
