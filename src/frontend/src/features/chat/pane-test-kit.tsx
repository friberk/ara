// Fixtures and a routed mount for the conversation pane tests. Not a test file itself.
import { StrictMode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { Citation, Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { WorkspaceContext, type WorkspaceContextValue } from '@/features/workspace/workspace-context'
import { testClient } from '@/test/render'
import { CurrentPath, PaneRoute } from './pane-test-routes'

export const luna = { key: 'gpt-5.6-luna', provider: 'openai', model_id: 'gpt-5.6-luna', display_name: 'Luna', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }
export const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
export const paper2: Paper = { id: 'p2', title: 'Dense passage retrieval', authors: ['Vladimir Karpukhin', 'Barlas Oguz'], year: 2020, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd2', metadata_provenance: {} }
/** A paper as a chat includes it, pinned to its active PDF unless overridden. */
export function included(source: Paper, overrides: Record<string, unknown> = {}) {
  return { paper_id: source.id, document_id: source.active_document_id ?? `${source.id}-pdf`, title: source.title, first_author: source.authors[0] ?? null, year: source.year, added_at: '2026-10-08T10:00:00Z', ...overrides }
}
export const settings = { 'GET /models': { items: [luna] }, 'GET /settings': { default_model: luna.key, reasoning_effort: 'low' } }
export const citation: Citation = { chunk_id: '12345678-1234-1234-1234-123456789abc', document_id: 'd1', page: 2, excerpt: 'A measured result from the document.' }
export const marker = `[source:${citation.chunk_id}]`
export function chatRow(id: string, overrides: Record<string, unknown> = {}) {
  return { id, paper_id: 'p1', papers: [included(paper)], title: 'Research question', title_source: 'auto', created_at: '2026-10-08T10:00:00Z', last_activity_at: '2026-10-08T12:00:00Z', message_count: 0, last_question_preview: null, ...overrides }
}
export function userMessage(id: string, content: string) { return { id, role: 'user', content, state: 'completed', model: null, reasoning_effort: null, citations: [], created_at: '2026-10-08T12:00:00Z' } }
export function assistantMessage(id: string, content: string, overrides: Record<string, unknown> = {}) {
  return { id, role: 'assistant', content, state: 'completed', model: luna.key, reasoning_effort: 'low', citations: [], created_at: '2026-10-08T12:00:01Z', ...overrides }
}
export function sse(frames: [string, unknown][]) {
  return new Response(frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}
export function workspaceValue(): WorkspaceContextValue {
  return { paper, view: 'chat', setView: vi.fn(), sourceRequest: null, showSource: vi.fn(), highlightOutcome: null, reportHighlight: vi.fn() }
}

/** `others` are the papers the route may switch to (by :paperId), as the workspace would load them. */
export function mount(path: string, { value = paper, others = [], workspace = workspaceValue(), strict = false, client = testClient() }: { value?: Paper; others?: Paper[]; workspace?: WorkspaceContextValue; strict?: boolean; client?: QueryClient } = {}) {
  const user = userEvent.setup()
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TooltipProvider>
          <GenerationSettingsProvider>
            <WorkspaceContext.Provider value={workspace}>
              <div style={{ height: 800 }}>
                <Routes>
                  <Route path="/papers/:paperId" element={<PaneRoute value={value} others={others} />} />
                  <Route path="/papers/:paperId/chats/:chatId" element={<PaneRoute value={value} others={others} />} />
                </Routes>
              </div>
              <CurrentPath />
            </WorkspaceContext.Provider>
          </GenerationSettingsProvider>
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
  render(strict ? <StrictMode>{tree}</StrictMode> : tree)
  return { user, client, workspace }
}
export async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  const input = await screen.findByRole('textbox', { name: 'Question about this paper' })
  await waitFor(() => expect(input).toBeEnabled())
  await user.type(input, question)
  await user.click(screen.getByRole('button', { name: 'Ask question' }))
}
