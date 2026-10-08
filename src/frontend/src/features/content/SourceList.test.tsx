import { screen, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { renderWithProviders } from '@/test/render'
import { SourceList } from './SourceList'

const cite = (chunk: string, page: number, document = 'd1'): Citation => ({ chunk_id: chunk, document_id: document, page, excerpt: `Excerpt ${chunk}.` })

test('Given several citations per page, Then each page is listed once in page order', () => {
  renderWithProviders(<SourceList documentId="d1" citations={[cite('a', 12), cite('b', 3), cite('c', 12), cite('d', 7), cite('e', 3)]} />)
  const sources = screen.getByRole('group', { name: 'Sources' })
  expect(within(sources).getAllByRole('button').map((button) => button.textContent)).toEqual(['p. 3', 'p. 7', 'p. 12'])
  expect(screen.queryByRole('alert')).toBeNull()
})

test('Given a citation from another document, Then it is withheld and the mismatch is reported', () => {
  renderWithProviders(<SourceList documentId="d1" citations={[cite('a', 2), cite('x', 5, 'other')]} />)
  expect(within(screen.getByRole('group', { name: 'Sources' })).getAllByRole('button').map((button) => button.textContent)).toEqual(['p. 2'])
  expect(screen.getByRole('alert')).toHaveTextContent('A citation could not be matched to this document.')
})

test('Given only foreign citations, Then no sources row renders but the mismatch is reported', () => {
  renderWithProviders(<SourceList documentId="d1" citations={[cite('x', 5, 'other')]} />)
  expect(screen.queryByRole('group', { name: 'Sources' })).toBeNull()
  expect(screen.getByRole('alert')).toHaveTextContent('A citation could not be matched to this document.')
})

test('Given no citations, Then nothing renders', () => {
  const { container } = renderWithProviders(<SourceList documentId="d1" citations={[]} />)
  expect(container).toBeEmptyDOMElement()
})

test('Given a keyboard user, Then every source can be reached and opened without a pointer', async () => {
  const onSelect = vi.fn()
  const citations = [cite('a', 4), cite('b', 9)]
  const { user } = renderWithProviders(<SourceList documentId="d1" citations={citations} onSelect={onSelect} />)
  await user.tab()
  expect(screen.getByRole('button', { name: 'Source, page 4' })).toHaveFocus()
  await user.tab()
  expect(screen.getByRole('button', { name: 'Source, page 9' })).toHaveFocus()
  await user.keyboard('{Enter}')
  await user.keyboard(' ')
  expect(onSelect).toHaveBeenCalledTimes(2)
  expect(onSelect).toHaveBeenLastCalledWith(citations[1])
})
