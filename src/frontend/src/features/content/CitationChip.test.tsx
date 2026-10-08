import { screen, waitFor } from '@testing-library/react'
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
  mockApi({ 'GET /documents/d1/chunks/c1': () => json({ code: 'CHUNK_NOT_FOUND', message: 'This source passage no longer exists.' }, 404) })
  const { user } = renderWithProviders(<CitationChip citation={citation} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This source passage no longer exists.')
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
