// Reader tabs for chats over several papers (ARA-088): another paper's citation opens its PDF in its own tab.
import { screen, waitFor, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { renderApp } from '@/test/render'

vi.mock('./PdfViewer', async () => {
  const { useEffect } = await import('react')
  return {
    default: function PdfViewerStub({ documentId, highlight, onDocumentLoad, bar }: import('./PdfViewer').PdfViewerProps) {
      useEffect(() => onDocumentLoad(12), [onDocumentLoad])
      return <div role="group" aria-label="PDF viewer">{bar}<p>{`Showing ${documentId}${highlight ? ` at page ${highlight.citation.page}` : ''}`}</p></div>
    },
  }
})

const own: Citation = { chunk_id: 'chunk-1', document_id: 'doc-1', page: 2, excerpt: 'Sparse recall is 0.61.' }
const dense = (page: number): Citation => ({ chunk_id: `chunk-d${page}`, document_id: 'doc-2', paper_id: 'p2', page, excerpt: 'Dense recall is 0.79.' })

vi.mock('@/features/chat', async () => {
  const { useWorkspace } = await import('./workspace-context')
  return {
    ConversationPane: function ConversationStub() {
      const { showSource } = useWorkspace()
      return (
        <section aria-label="Conversation">
          <button type="button" onClick={() => showSource(dense(4))}>Cite page 4 of the second paper</button>
          <button type="button" onClick={() => showSource(dense(6))}>Cite page 6 of the second paper</button>
          <button type="button" onClick={() => showSource(own)}>Cite page 2 of this paper</button>
        </section>
      )
    },
  }
})

const base = { abstract: null, doi: null, sources: [], document_status: 'ready', metadata_provenance: {} }
const paper = { ...base, id: 'p1', title: 'Evidence based research', authors: ['A. Author'], year: 2024, active_document_id: 'doc-1' }
const second = { ...base, id: 'p2', title: 'Dense passage retrieval', authors: ['Vladimir Karpukhin', 'Barlas Oguz'], year: 2020, active_document_id: 'doc-2' }

// jsdom has no layout, so react-resizable-panels would take every pointerdown for its split handle and stop Radix tabs
// from activating (as in workspace.test.tsx). Move the handle away.
const boundingRect = HTMLElement.prototype.getBoundingClientRect
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute('data-separator') ? new DOMRect(-500, -500, 1, 1) : boundingRect.call(this)
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function visibleViewer() {
  return screen.getAllByRole('group', { name: 'PDF viewer' }).find((viewer) => viewer.closest('[hidden]') === null)
}

test('Given a citation to another paper, When it is shown, Then its PDF opens in a new reader tab at the cited page, and later citations focus the right tab', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /papers/p2': second })
  const { user } = renderApp('/papers/p1')
  expect(await screen.findByText('Showing doc-1')).toBeVisible()
  expect(screen.queryByRole('tablist', { name: 'Open PDFs' })).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Cite page 4 of the second paper' }))
  const tabs = await screen.findByRole('tablist', { name: 'Open PDFs' })
  expect(within(tabs).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Author 2024', 'Karpukhin 2020'])
  await waitFor(() => expect(within(tabs).getByRole('tab', { name: 'Karpukhin 2020' })).toHaveAttribute('aria-selected', 'true'))
  await waitFor(() => expect(visibleViewer()).toHaveTextContent('Showing doc-2 at page 4'))

  await user.click(screen.getByRole('button', { name: 'Cite page 2 of this paper' }))
  await waitFor(() => expect(within(tabs).getByRole('tab', { name: 'Author 2024' })).toHaveAttribute('aria-selected', 'true'))
  expect(visibleViewer()).toHaveTextContent('Showing doc-1 at page 2')

  await user.click(screen.getByRole('button', { name: 'Cite page 6 of the second paper' }))
  await waitFor(() => expect(visibleViewer()).toHaveTextContent('Showing doc-2 at page 6'))
  expect(within(tabs).getAllByRole('tab')).toHaveLength(2)

  // Switching tabs by hand keeps each paper's PDF open.
  await user.click(within(tabs).getByRole('tab', { name: 'Author 2024' }))
  await waitFor(() => expect(visibleViewer()).toHaveTextContent('Showing doc-1'))
})

test('Given two reader tabs, When tabs are closed, Then any tab can be closed except the last one', async () => {
  mockApi({ 'GET /papers/p1': paper, 'GET /papers/p2': second })
  const { user } = renderApp('/papers/p1')
  await screen.findByText('Showing doc-1')
  await user.click(screen.getByRole('button', { name: 'Cite page 4 of the second paper' }))
  const tabs = await screen.findByRole('tablist', { name: 'Open PDFs' })
  await user.click(within(tabs).getByRole('button', { name: 'Close Author 2024' }))
  await waitFor(() => expect(within(tabs).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Karpukhin 2020']))
  expect(visibleViewer()).toHaveTextContent('Showing doc-2 at page 4')
  expect(within(tabs).queryByRole('button', { name: /^Close/ })).not.toBeInTheDocument()

  // A citation of the workspace's own paper opens its tab again.
  await user.click(screen.getByRole('button', { name: 'Cite page 2 of this paper' }))
  await waitFor(() => expect(within(tabs).getAllByRole('tab')).toHaveLength(2))
  expect(visibleViewer()).toHaveTextContent('Showing doc-1 at page 2')
})
