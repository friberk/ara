import { screen, within } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PaperPicker } from './PaperPicker'

const paper = (id: string, title: string, document_status: string) => ({ id, title, authors: ['Ada Researcher'], year: 2024, abstract: null, doi: null, sources: [], document_status, active_document_id: document_status === 'ready' ? `d-${id}` : null, metadata_provenance: {} })
afterEach(() => vi.unstubAllGlobals())

test('Given library papers, Then only papers with a processed PDF can be chosen to ask about', async () => {
  mockApi({ 'GET /papers': { items: [paper('p1', 'Ready paper', 'ready'), paper('p2', 'Paper without PDF', 'metadata_only')] } })
  const onSelect = vi.fn()
  const { user } = renderWithProviders(<TooltipProvider><PaperPicker onSelect={onSelect} /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  const blocked = await screen.findByRole('option', { name: /Paper without PDF/ })
  expect(blocked).toHaveAttribute('aria-disabled', 'true')
  expect(blocked).toHaveTextContent('PDF needed')
  await user.click(screen.getByRole('option', { name: /Ready paper/ }))
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }))
  expect(screen.queryByRole('option', { name: /Ready paper/ })).not.toBeInTheDocument()
})

test('Given papers already mentioned, Then they show as checked, choosing one again hands it back to mention again, and there is no limit on how many', async () => {
  const items = [1, 2, 3, 4, 5, 6].map((n) => paper(`p${n}`, `Paper ${n}`, 'ready'))
  mockApi({ 'GET /papers': { items } })
  const onSelect = vi.fn()
  const { user, rerender } = renderWithProviders(<TooltipProvider><PaperPicker onSelect={onSelect} selected={['p1']} /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  const added = await screen.findByRole('option', { name: /Paper 1/ })
  // Selection shows the stock way: a check and a checked state, with no helper text.
  expect(added).toHaveAttribute('data-checked', 'true')
  expect(added).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByRole('option', { name: /Paper 2/ })).toHaveAttribute('aria-checked', 'false')
  expect(screen.queryByText(/Added|Choose again/)).not.toBeInTheDocument()
  await user.click(added)
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'p1' }))
  rerender(<TooltipProvider><PaperPicker onSelect={onSelect} selected={['p1', 'p2', 'p3', 'p4', 'p5']} /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  const sixth = await screen.findByRole('option', { name: /Paper 6/ })
  expect(sixth).not.toHaveAttribute('aria-disabled', 'true')
  await user.click(sixth)
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'p6' }))
})

test('Given library papers, Then each row gives a short citation under its title, or its PDF status, and search matches authors, year and venue', async () => {
  const vaswani = { ...paper('p1', 'Attention Is All You Need', 'ready'), authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'], year: 2017, venue: 'NeurIPS' }
  const karpukhin = { ...paper('p2', 'Dense Passage Retrieval', 'ready'), authors: ['Vladimir Karpukhin', 'Barlas Oguz'], year: 2020, venue: 'EMNLP' }
  const bare = { ...paper('p3', 'Untitled notes', 'ready'), authors: [], year: null, venue: null }
  const waiting = { ...paper('p4', 'Paper being read', 'processing'), authors: ['Ada Researcher'], year: 2024 }
  mockApi({ 'GET /papers': { items: [vaswani, karpukhin, bare, waiting] } })
  const { user } = renderWithProviders(<TooltipProvider><PaperPicker onSelect={vi.fn()} /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  expect(await screen.findByRole('option', { name: /Attention Is All You Need/ })).toHaveTextContent('Vaswani et al. (2017), NeurIPS')
  expect(screen.getByRole('option', { name: /Dense Passage Retrieval/ })).toHaveTextContent('Karpukhin & Oguz (2020), EMNLP')
  const untitled = screen.getByRole('option', { name: /Untitled notes/ })
  expect(untitled.textContent).toBe('Untitled notes')
  // A row that cannot be chosen keeps its citation and shows its status in a badge.
  const waitingRow = screen.getByRole('option', { name: /Paper being read/ })
  expect(waitingRow).toHaveTextContent('Researcher (2024)')
  expect(within(waitingRow).getByText('Preparing PDF').closest('[data-slot="badge"]')).not.toBeNull()
  expect(screen.queryByText(/undefined|null|Ready to ask/)).not.toBeInTheDocument()
  expect(document.body.textContent).not.toContain('·')

  const search = screen.getByPlaceholderText('Find a paper in your library')
  await user.type(search, 'Shazeer')
  expect(screen.getAllByRole('option').map((option) => option.getAttribute('data-value'))).toEqual([expect.stringContaining('Attention Is All You Need')])
  await user.clear(search)
  await user.type(search, 'emnlp')
  expect(screen.getByRole('option', { name: /Dense Passage Retrieval/ })).toBeVisible()
  expect(screen.queryByRole('option', { name: /Attention Is All You Need/ })).not.toBeInTheDocument()
  await user.clear(search)
  await user.type(search, '2017')
  expect(screen.getAllByRole('option')).toHaveLength(1)
})
