import { screen, waitFor, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { json, mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { CitationChip } from './CitationChip'

const citation: Citation = { chunk_id: 'c1', document_id: 'd1', page: 7, excerpt: 'Short excerpt.' }
const fullExcerpt = 'Multi-head attention allows the model to jointly attend to information from different representation subspaces.'

test('Given a citation, Then a compact page chip names its source', () => {
  renderWithProviders(<CitationChip citation={citation} />)
  expect(screen.getByRole('button', { name: 'Source, page 7' })).toHaveTextContent('p. 7')
})

test('Given onSelect, When the chip is clicked, Then the citation is handed over and no dialog opens', async () => {
  const onSelect = vi.fn()
  const { calls } = mockApi({})
  const { user } = renderWithProviders(<CitationChip citation={citation} onSelect={onSelect} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(onSelect).toHaveBeenCalledWith(citation, undefined)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(calls.filter((call) => call.path.includes('/chunks/'))).toHaveLength(0)
})

test('Given a claim, When the chip is clicked, Then onSelect receives the citation with that claim', async () => {
  const onSelect = vi.fn()
  const { user } = renderWithProviders(<CitationChip citation={citation} claim="Attention heads capture syntax." onSelect={onSelect} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(onSelect).toHaveBeenCalledWith(citation, 'Attention heads capture syntax.')
})

test('Given no onSelect, When the chip is clicked, Then a dialog shows the verified excerpt and links to the PDF page', async () => {
  const { calls } = mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  expect(calls).toHaveLength(0)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  const dialog = await screen.findByRole('dialog', { name: 'Source on page 7' })
  expect(await screen.findByText(fullExcerpt)).toBeVisible()
  expect(dialog).toContainElement(screen.getByRole('link', { name: 'Open PDF at page 7' }))
  expect(screen.getByRole('link', { name: 'Open PDF at page 7' })).toHaveAttribute('href', '/api/v1/documents/d1/download#page=7')
  expect(calls.map((call) => call.path)).toEqual(['/documents/d1/chunks/c1'])
})

test('Given the dialog is open, When the reader closes it, Then focus returns to the chip without a preview', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  const chip = screen.getByRole('button', { name: 'Source, page 7' })
  await user.click(chip)
  await screen.findByRole('dialog', { name: 'Source on page 7' })
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(chip).toHaveFocus()
  await new Promise((resolve) => setTimeout(resolve, 400))
  expect(screen.queryByText(fullExcerpt)).toBeNull()
})

test('Given a source that does not match the citation, When the dialog opens, Then an error offers a retry', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, page: 8 } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This citation could not be matched to its source.')
  expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible()
})

test('Given a server error, When the dialog opens, Then the server message is shown', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': () => json({ code: 'SERVICE_UNAVAILABLE', message: 'The library is temporarily unavailable.' }, 503) })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('The library is temporarily unavailable.')
})

// Re-indexing a paper replaces its passages (ARA-071), so older answers cite chunks that no longer exist.
const replaced = () => json({ code: 'CITATION_NOT_FOUND', message: 'This source excerpt does not belong to the selected document.' }, 404)

test('Given a passage replaced by re-indexing, When the dialog opens, Then the excerpt saved with the answer is shown', async () => {
  const saved: Citation = { ...citation, excerpt: fullExcerpt }
  const { calls } = mockApi({ 'GET /documents/d1/chunks/c1': replaced })
  const { user } = renderWithProviders(<CitationChip citation={saved} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  const dialog = await screen.findByRole('dialog', { name: 'Source on page 7' })
  expect(await within(dialog).findByText(fullExcerpt)).toBeVisible()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(calls.map((call) => call.path)).toEqual(['/documents/d1/chunks/c1'])
})

test('Given a passage replaced by re-indexing, When previewed, Then the saved excerpt shows instead of an error', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': replaced })
  const { user } = renderWithProviders(<CitationChip citation={{ ...citation, excerpt: fullExcerpt }} />)
  await user.hover(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(await screen.findByText(fullExcerpt)).toBeVisible()
  expect(screen.queryByRole('alert')).toBeNull()
})

test('Given a pointer resting on the chip, Then a preview loads the excerpt only once it opens', async () => {
  const { calls } = mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  expect(calls).toHaveLength(0)
  await user.hover(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(await screen.findByText('Page 7')).toBeVisible()
  expect(await screen.findByText(fullExcerpt)).toBeVisible()
  expect(calls.map((call) => call.path)).toEqual(['/documents/d1/chunks/c1'])
})

const markdownExcerpt = '# **Results**\n\n|Model|Recall@10|\n|---|---|\n|BM25|0.61|'

test('Given a Markdown passage, When the preview opens, Then it reads as text without markup', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: markdownExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.hover(screen.getByRole('button', { name: 'Source, page 7' }))
  const preview = (await screen.findByText(/Model Recall@10/)).closest('p')!
  expect(preview).toHaveTextContent('Results Model Recall@10 BM25 0.61')
  expect(preview.textContent).not.toMatch(/[#*|]|---/)
})

test('Given a Markdown passage, When the dialog opens, Then its heading and table render as formatted text', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: markdownExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  const dialog = await screen.findByRole('dialog', { name: 'Source on page 7' })
  expect(await within(dialog).findByRole('heading', { name: 'Results' })).toBeVisible()
  expect(within(dialog).getByRole('cell', { name: '0.61' })).toBeVisible()
  expect(dialog.textContent).not.toMatch(/[#*|]|---/)
})

test('Given a device that cannot hover, Then no preview opens and a tap still reads the source', async () => {
  const matchMedia = window.matchMedia
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({ ...matchMedia(query), matches: query === '(hover: none)' }))
  const { calls } = mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.hover(screen.getByRole('button', { name: 'Source, page 7' }))
  await new Promise((resolve) => setTimeout(resolve, 400))
  expect(screen.queryByText('Page 7')).toBeNull()
  expect(calls).toHaveLength(0)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(await screen.findByRole('dialog', { name: 'Source on page 7' })).toHaveTextContent(fullExcerpt)
  vi.mocked(window.matchMedia).mockRestore()
})

// Test-after (ARA-035 audit): the preview pauses shipped before tests covered them.
test('Given onSelect, When the hovered chip is clicked, Then no preview opens over the result', async () => {
  const { calls } = mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} onSelect={() => {}} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  await new Promise((resolve) => setTimeout(resolve, 400))
  expect(screen.queryByText('Page 7')).toBeNull()
  expect(calls).toHaveLength(0)
})

test('Given a tap on a device that can also hover, Then the focus it gives opens no preview', async () => {
  const { calls } = mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} onSelect={() => {}} />)
  const chip = screen.getByRole('button', { name: 'Source, page 7' })
  await user.pointer({ keys: '[TouchA]', target: chip })
  expect(chip).toHaveFocus()
  await new Promise((resolve) => setTimeout(resolve, 400))
  expect(screen.queryByText('Page 7')).toBeNull()
  expect(calls).toHaveLength(0)
})

test('Given keyboard focus on the chip, Then the same preview opens', async () => {
  mockApi({ 'GET /documents/d1/chunks/c1': { ...citation, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.tab()
  expect(screen.getByRole('button', { name: 'Source, page 7' })).toHaveFocus()
  expect(await screen.findByText(fullExcerpt)).toBeVisible()
})

// Passage provenance (ARA-075): a chunk can span pages and sits under a section heading.
const passage: Citation = { chunk_id: 'c2', document_id: 'd1', page: 6, page_end: null, section: 'Results > Open-domain QA', kind: 'text', bboxes: [], excerpt: 'Short excerpt.' }

test('Given a passage under a section, When previewed, Then its heading path shows above the excerpt and its last heading names the chip', async () => {
  mockApi({ 'GET /documents/d1/chunks/c2': { ...passage, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={passage} />)
  const chip = screen.getByRole('button', { name: 'Source, page 6, Open-domain QA' })
  expect(chip).toHaveTextContent(/^p\. 6$/)
  await user.hover(chip)
  const section = await screen.findByText('Results > Open-domain QA')
  const excerpt = await screen.findByText(fullExcerpt)
  expect(section.compareDocumentPosition(excerpt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.queryByText('Table')).toBeNull()
})

test('Given a table passage, When previewed, Then the preview says it is a table', async () => {
  const table: Citation = { ...passage, section: 'Results', kind: 'table' }
  mockApi({ 'GET /documents/d1/chunks/c2': table })
  const { user } = renderWithProviders(<CitationChip citation={table} />)
  await user.hover(screen.getByRole('button', { name: 'Source, page 6, Results' }))
  expect(await screen.findByText('Table')).toBeVisible()
  expect(screen.getByText('Page 6')).toBeVisible()
})

test('Given a passage spanning pages 5 and 6, Then the chip reads p. 5–6 and the dialog names both pages', async () => {
  const spanning: Citation = { ...passage, page: 5, page_end: 6, section: null }
  mockApi({ 'GET /documents/d1/chunks/c2': { ...spanning, excerpt: fullExcerpt } })
  const { user } = renderWithProviders(<CitationChip citation={spanning} />)
  const chip = screen.getByRole('button', { name: 'Source, pages 5–6' })
  expect(chip).toHaveTextContent(/^p\. 5–6$/)
  await user.click(chip)
  expect(await screen.findByRole('dialog', { name: 'Source on pages 5–6' })).toHaveTextContent(fullExcerpt)
  expect(screen.getByRole('link', { name: 'Open PDF at page 5' })).toHaveAttribute('href', '/api/v1/documents/d1/download#page=5')
})

test('Given page_end on the same page, Then the chip names a single page', () => {
  renderWithProviders(<CitationChip citation={{ ...passage, page_end: 6, section: null }} />)
  expect(screen.getByRole('button', { name: 'Source, page 6' })).toHaveTextContent(/^p\. 6$/)
})
