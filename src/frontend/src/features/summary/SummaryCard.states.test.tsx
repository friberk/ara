// Characterization tests written AFTER the implementation (ARA-036), for behaviour that shipped without a test
// of its own. Each one was checked by temporarily breaking the behaviour it covers and watching it fail.
import { screen, within } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { SummaryCard } from '.'

const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
afterEach(() => vi.unstubAllGlobals())

test('Given a summary job that fails, Then the reason is shown inline and Generate summary can be tried again', async () => {
  let posts = 0
  mockApi({
    'GET /models': { items: [luna] },
    'GET /settings': { default_model: luna.key, reasoning_effort: 'low' },
    'POST /papers/p1/summaries': () => { posts++; return json({ job_id: 'j3', summary_id: null }) },
    'GET /jobs/j3': { id: 'j3', kind: 'summary', state: 'failed', stage: 'failed', progress: 30, attempts: 1, generation: 1, result: null, error_code: 'SUMMARY_FAILED', error_message: 'The PDF text could not be summarized.', available_at: '2026-10-08T12:00:00Z', created_at: '2026-10-08T12:00:00Z', updated_at: '2026-10-08T12:00:00Z', error: { code: 'SUMMARY_FAILED', message: 'The PDF text could not be summarized.' }, paper_id: 'p1', paper_title: paper.title },
  })
  const { user } = renderWithProviders(<TooltipProvider><GenerationSettingsProvider><SummaryCard paper={paper} /></GenerationSettingsProvider></TooltipProvider>)
  const card = await screen.findByRole('article', { name: 'Paper summary' })
  const generate = await within(card).findByRole('button', { name: 'Generate summary' })
  await vi.waitFor(() => expect(generate).toBeEnabled())
  await user.click(generate)
  expect(await within(card).findByRole('alert')).toHaveTextContent('The summary could not be generated. The PDF text could not be summarized.')
  await user.click(within(card).getByRole('button', { name: 'Try again' }))
  await vi.waitFor(() => expect(posts).toBe(2))
})
