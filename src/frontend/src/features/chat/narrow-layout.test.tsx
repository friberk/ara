// Defects from the ARA-097 design review, on a 390px screen. jsdom has no layout, so these pin the CSS that fixes them;
// e2e/workspace.spec.ts measures the real overflow in a browser.
import { screen, within } from '@testing-library/react'
import { mockApi } from '@/test/fetch-routes'
import { assistantMessage, chatRow, citation, included, marker, mount, paper, paper2, settings, userMessage } from './pane-test-kit'

afterEach(() => vi.unstubAllGlobals())

const long = 'Runs live under https://example.org/research/notebooks/2026/traceable-research-systems/appendix-b/runs/7f3c9a1e2b4d6f8091a2b3c4 and `traceable_research_systems.evaluation.pipeline.ProvenanceAwareCitationValidatorConfiguration`.'
const table = '| Condition | Verification time | Accuracy | Participants | Notes |\n|---|---|---|---|---|\n| Traceable answers with page-level provenance | 3.1 minutes | 86 percent | 24 | Highlights jumped to the sentence |'

test('Given an answer with a long link, a long identifier and a wide table, Then its column cannot grow past the thread, so they wrap or scroll inside it', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { message_count: 2 })] }, 'GET /chats/c1/messages': { items: [userMessage('u1', 'Where are the runs?'), assistantMessage('m1', `${long} ${marker}\n\n${table}`, { citations: [citation] })] } })
  mount('/papers/p1/chats/c1')
  const answer = await screen.findByRole('article', { name: 'Assistant message' })
  // The answer is a grid; an implicit track grows to the widest word, so the column is minmax(0, 1fr).
  expect(answer).toHaveClass('grid-cols-1')
  expect(within(answer).getByRole('table').closest('.overflow-x-auto')).not.toBeNull()
})

test('Given a chat over several papers, Then the chip row above the thread is opaque', async () => {
  mockApi({ ...settings, 'GET /chats': { items: [chatRow('c1', { papers: [included(paper), included(paper2)] })] }, 'GET /chats/c1/messages': { items: [] } })
  mount('/papers/p1/chats/c1')
  expect(await screen.findByRole('list', { name: 'Papers in this conversation' })).toHaveClass('bg-background')
})
