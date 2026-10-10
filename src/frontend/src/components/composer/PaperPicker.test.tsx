import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PaperChips, PaperContextChip, PaperPicker } from './PaperPicker'

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

test('Given a chosen paper, Then its chip names it and can be removed', async () => {
  const onRemove = vi.fn()
  const user = userEvent.setup()
  renderWithProviders(<PaperContextChip paper={{ title: 'Ready paper' }} onRemove={onRemove} />)
  expect(screen.getByText('Ready paper')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Stop asking about this paper' }))
  expect(onRemove).toHaveBeenCalledTimes(1)
})

test('Given papers already chosen, Then they show as added, choosing one again removes it, and there is no limit on how many', async () => {
  const items = [1, 2, 3, 4, 5, 6].map((n) => paper(`p${n}`, `Paper ${n}`, 'ready'))
  mockApi({ 'GET /papers': { items } })
  const onSelect = vi.fn()
  const { user, rerender } = renderWithProviders(<TooltipProvider><PaperPicker onSelect={onSelect} selected={['p1']} /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  const added = await screen.findByRole('option', { name: /Paper 1/ })
  expect(added).toHaveTextContent('Added. Choose again to remove.')
  await user.click(added)
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'p1' }))
  rerender(<TooltipProvider><PaperPicker onSelect={onSelect} selected={['p1', 'p2', 'p3', 'p4', 'p5']} /></TooltipProvider>)
  await user.click(screen.getByRole('button', { name: 'Ask about a library paper' }))
  const sixth = await screen.findByRole('option', { name: /Paper 6/ })
  expect(sixth).not.toHaveAttribute('aria-disabled', 'true')
  await user.click(sixth)
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'p6' }))
})

test('Given many chosen papers, Then a few show as chips and the rest collapse into a list where any can be removed', async () => {
  const chosen = [1, 2, 3, 4, 5].map((n) => ({ id: `p${n}`, title: `Paper ${n}` }))
  const onRemove = vi.fn()
  const user = userEvent.setup()
  renderWithProviders(<TooltipProvider><PaperChips papers={chosen} onRemove={onRemove} /></TooltipProvider>)
  for (const title of ['Paper 1', 'Paper 2', 'Paper 3']) expect(screen.getByText(title)).toBeVisible()
  expect(screen.queryByText('Paper 5')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '+2 more' }))
  const list = await screen.findByRole('list', { name: 'Chosen papers' })
  await user.click(within(list).getByRole('button', { name: 'Remove Paper 5' }))
  expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 'p5' }))
})
