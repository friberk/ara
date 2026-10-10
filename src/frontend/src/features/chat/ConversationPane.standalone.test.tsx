import { screen, within } from '@testing-library/react'
import type { Paper } from '@/api/types'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { TooltipProvider } from '@/components/ui/tooltip'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { ConversationPane } from '.'

// Outside the paper workspace (no WorkspaceContext) with the real content module.
const models = ['luna', 'terra'].map((name) => ({ key: `gpt-5.6-${name}`, provider: 'openai', model_id: `gpt-5.6-${name}`, display_name: name === 'luna' ? 'Luna' : 'Terra', status: 'available', reasoning_efforts: ['low', 'high'], supports_streaming: true, supports_structured_output: true, context_window: 32000 }))
const paper: Paper = { id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: 'd1', metadata_provenance: {} }
const chat = { id: 'stored-chat', paper_id: 'p1', papers: [{ paper_id: 'p1', document_id: 'd1', title: paper.title, first_author: 'A. Author', year: 2024, added_at: '2026-10-08T00:00:00Z' }], title: 'Earlier discussion', title_source: 'manual', created_at: '2026-10-08T00:00:00Z', last_activity_at: '2026-10-08T00:00:00Z', message_count: 2, last_question_preview: 'What is saved?' }
afterEach(() => vi.unstubAllGlobals())

test('Given a stored Luna answer and a Terra default, When the chat opens, Then the composer adopts Luna and the answer keeps its stored Luna and low reasoning', async () => {
  const answer = { id: 'stored-luna-answer', role: 'assistant', content: 'A saved response from this paper.', state: 'completed', model: 'gpt-5.6-luna', reasoning_effort: 'low', citations: [], created_at: '2026-10-08T00:00:00Z' }
  mockApi({
    'GET /models': { items: models },
    'GET /settings': { default_model: 'gpt-5.6-terra', reasoning_effort: 'high' },
    'GET /chats': { items: [chat] },
    'GET /chats/stored-chat/messages': { items: [answer] },
  })
  renderWithProviders(<TooltipProvider><GenerationSettingsProvider><div style={{ height: 800 }}><ConversationPane paper={paper} chatId="stored-chat" /></div></GenerationSettingsProvider></TooltipProvider>)
  const reply = await screen.findByRole('article', { name: 'Assistant message' })
  expect(await within(reply).findByText('A saved response from this paper.')).toBeVisible()
  expect(await screen.findByRole('button', { name: 'Model: Luna, Low reasoning' })).toBeVisible()
  expect(within(reply).getByText('Luna')).toBeVisible()
  expect(within(reply).getByText('Low reasoning')).toBeVisible()
  expect(within(reply).queryByText('Terra')).not.toBeInTheDocument()
  expect(within(reply).queryByText('High reasoning')).not.toBeInTheDocument()
  expect(within(reply).getByRole('button', { name: 'Copy answer' })).toBeVisible()
})
