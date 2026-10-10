import { screen, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { renderWithProviders } from '@/test/render'
import { SourceList } from './SourceList'

const cite = (chunk: string, page: number, document = 'd1'): Citation => ({ chunk_id: chunk, document_id: document, page, excerpt: `Excerpt ${chunk}.` })

test('Given several passages per page, Then each cited passage is listed once in page order (ARA-075)', () => {
  renderWithProviders(<SourceList documents={new Set(['d1'])} citations={[cite('a', 12), cite('b', 3), cite('c', 12), cite('d', 7), cite('e', 3), cite('a', 12)]} />)
  const sources = screen.getByRole('group', { name: 'Sources' })
  expect(within(sources).getAllByRole('button').map((button) => button.textContent)).toEqual(['p. 3', 'p. 3', 'p. 7', 'p. 12', 'p. 12'])
  expect(screen.queryByRole('alert')).toBeNull()
})

test('Given two passages on page 6 from different sections, Then each has a chip named by its section (ARA-075)', () => {
  const citations = [{ ...cite('a', 6), section: 'Results > Open-domain QA' }, { ...cite('b', 6), section: 'Results > Reading comprehension' }]
  renderWithProviders(<SourceList documents={new Set(['d1'])} citations={citations} />)
  const chips = within(screen.getByRole('group', { name: 'Sources' })).getAllByRole('button')
  expect(chips.map((chip) => chip.textContent)).toEqual(['p. 6', 'p. 6'])
  expect(chips.map((chip) => chip.getAttribute('aria-label'))).toEqual(['Source, page 6, Open-domain QA', 'Source, page 6, Reading comprehension'])
})

test('Given a passage spanning pages 5 and 6, Then its chip reads p. 5–6 and sorts by its first page (ARA-075)', () => {
  renderWithProviders(<SourceList documents={new Set(['d1'])} citations={[cite('x', 7), { ...cite('y', 5), page_end: 6 }]} />)
  const chips = within(screen.getByRole('group', { name: 'Sources' })).getAllByRole('button')
  expect(chips.map((chip) => chip.textContent)).toEqual(['p. 5–6', 'p. 7'])
  expect(chips[0]).toHaveAccessibleName('Source, pages 5–6')
})

test('Given a citation from another document, Then it is withheld and the mismatch is reported', () => {
  renderWithProviders(<SourceList documents={new Set(['d1'])} citations={[cite('a', 2), cite('x', 5, 'other')]} />)
  expect(within(screen.getByRole('group', { name: 'Sources' })).getAllByRole('button').map((button) => button.textContent)).toEqual(['p. 2'])
  expect(screen.getByRole('alert')).toHaveTextContent('A citation could not be matched to this document.')
})

test('Given only foreign citations, Then no sources row renders but the mismatch is reported', () => {
  renderWithProviders(<SourceList documents={new Set(['d1'])} citations={[cite('x', 5, 'other')]} />)
  expect(screen.queryByRole('group', { name: 'Sources' })).toBeNull()
  expect(screen.getByRole('alert')).toHaveTextContent('A citation could not be matched to this document.')
})

test('Given no citations, Then nothing renders', () => {
  const { container } = renderWithProviders(<SourceList documents={new Set(['d1'])} citations={[]} />)
  expect(container).toBeEmptyDOMElement()
})

test('Given a keyboard user, Then every source can be reached and opened without a pointer', async () => {
  const onSelect = vi.fn()
  const citations = [cite('a', 4), cite('b', 9)]
  const { user } = renderWithProviders(<SourceList documents={new Set(['d1'])} citations={citations} onSelect={onSelect} />)
  await user.tab()
  expect(screen.getByRole('button', { name: 'Source, page 4' })).toHaveFocus()
  await user.tab()
  expect(screen.getByRole('button', { name: 'Source, page 9' })).toHaveFocus()
  await user.keyboard('{Enter}')
  await user.keyboard(' ')
  expect(onSelect).toHaveBeenCalledTimes(2)
  expect(onSelect).toHaveBeenLastCalledWith(citations[1], undefined)
})

const chunk = (n: number) => `${String(n).repeat(8)}-1111-4111-8111-111111111111`
const lettered = 'abcdefab-cdef-4abc-8def-abcdefabcdef'

test('Given the answer the sources support, When a passage chip is opened, Then its claim is the sentences that cite that passage (ARA-075)', async () => {
  const onSelect = vi.fn()
  const citations = [cite(chunk(1), 4), cite(chunk(2), 9), cite(lettered, 4)]
  const context = [
    `Attention heads capture syntax [source:${chunk(1)}]. Convolutions are costly. [source:${chunk(2)}]`,
    '',
    `- Heads also track **semantics** [source:${lettered.toUpperCase()}]`,
  ].join('\n')
  const { user } = renderWithProviders(<SourceList documents={new Set(['d1'])} citations={citations} context={context} onSelect={onSelect} />)
  const [syntax, semantics] = screen.getAllByRole('button', { name: 'Source, page 4' })
  await user.click(syntax!)
  expect(onSelect).toHaveBeenLastCalledWith(citations[0], 'Attention heads capture syntax')
  await user.click(semantics!)
  expect(onSelect).toHaveBeenLastCalledWith(citations[2], 'Heads also track **semantics**')
  await user.click(screen.getByRole('button', { name: 'Source, page 9' }))
  expect(onSelect).toHaveBeenLastCalledWith(citations[1], 'Convolutions are costly.')
})

test('Given a page that no marker in the text cites, When its chip is opened, Then the claim is the whole text without markers', async () => {
  const onSelect = vi.fn()
  const citations = [cite(chunk(1), 4), cite(chunk(5), 2)]
  const context = `Heads capture syntax [source:${chunk(1)}]. They also track **semantics**.`
  const { user } = renderWithProviders(<SourceList documents={new Set(['d1'])} citations={citations} context={context} onSelect={onSelect} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 2' }))
  expect(onSelect).toHaveBeenCalledWith(citations[1], 'Heads capture syntax. They also track **semantics**.')
})
