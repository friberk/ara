import { render } from '@testing-library/react'
import { PaperCitation } from './PaperCitation'

const han = ['Seunghun Han', 'Wook Shin', 'Jun-Hyeok Park']
const venue = 'USENIX Security Symposium'
function line(authors: string[], year: number | null, venueName: string | null) {
  const { container } = render(<PaperCitation paper={{ authors, year, venue: venueName }} />)
  return container
}

test.each([
  [han, 2018, venue, 'Han et al. (2018), USENIX Security Symposium'],
  [han, 2018, null, 'Han et al. (2018)'],
  [han, null, venue, 'Han et al., USENIX Security Symposium'],
  [[], 2018, venue, '2018, USENIX Security Symposium'],
  [['Seunghun Han', 'Wook Shin'], null, null, 'Han & Shin'],
  [['Seunghun Han'], null, null, 'Han'],
  [[], 2018, null, '2018'],
  [[], null, venue, 'USENIX Security Symposium'],
])('Given %j, %s and %s, Then the citation reads like APA or Harvard', (authors, year, venueName, expected) => {
  const container = line(authors as string[], year as number | null, venueName as string | null)
  expect(container).toHaveTextContent(expected as string, { normalizeWhitespace: true })
  expect(container.textContent).not.toMatch(/[·•|]/)
})

test('Given no authors, year or venue, Then there is no citation line', () => {
  expect(line([], null, '  ').innerHTML).toBe('')
})

test('Given a long venue, Then only the italic venue truncates and keeps its full name; authors and year stay whole', () => {
  const container = line(han, 2018, venue)
  const venueText = container.querySelector('cite')!
  expect(venueText).toHaveTextContent(venue)
  expect(venueText).toHaveClass('italic', 'truncate', 'min-w-0')
  expect(venueText).toHaveAttribute('title', venue)
  const lead = venueText.previousElementSibling!
  expect(lead).toHaveTextContent('Han et al. (2018),')
  expect(lead).toHaveClass('shrink-0', 'whitespace-nowrap')
  expect(lead).not.toHaveClass('truncate')
  expect(container.querySelector('.tabular')).toHaveTextContent('2018')
})
