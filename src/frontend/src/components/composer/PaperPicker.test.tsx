import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PaperContextChip, PaperPicker } from './PaperPicker'

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
