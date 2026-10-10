import { authorShort, citationLine, mentionName, shortPaperName } from './paper-names'

const paper = (authors: string[], year: number | null = null, venue: string | null = null) => ({ title: 'Attention Is All You Need', authors, year, venue })

test('Given 0, 1, 2 or 3+ authors, Then the author part reads like a citation', () => {
  expect(authorShort([])).toBe('')
  expect(authorShort(['Ashish Vaswani'])).toBe('Vaswani')
  expect(authorShort(['Ashish Vaswani', 'Noam Shazeer'])).toBe('Vaswani & Shazeer')
  expect(authorShort(['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'])).toBe('Vaswani et al.')
  expect(authorShort(['Vaswani, Ashish', 'Shazeer, Noam'])).toBe('Vaswani & Shazeer')
  expect(authorShort(['  ', 'Noam Shazeer'])).toBe('Shazeer')
})

test('Given what a paper has, Then the citation parts are the short authors, the year and the venue, empty when missing', () => {
  const eight = ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit', 'Llion Jones', 'Aidan Gomez', 'Lukasz Kaiser', 'Illia Polosukhin']
  expect(citationLine(paper(eight, 2017, 'NeurIPS'))).toEqual({ authors: 'Vaswani et al.', year: '2017', venue: 'NeurIPS' })
  expect(citationLine(paper(['Ashish Vaswani'], 2017))).toEqual({ authors: 'Vaswani', year: '2017', venue: '' })
  expect(citationLine(paper([], null, '  '))).toEqual({ authors: '', year: '', venue: '' })
})

test('Given one naming source, Then chips and mentions name a paper by its first author and year', () => {
  expect(shortPaperName({ title: 'Attention Is All You Need', first_author: 'Ashish Vaswani', year: 2017 })).toBe('Vaswani 2017')
  expect(mentionName(paper(['Ashish Vaswani', 'Noam Shazeer'], 2017))).toBe('Vaswani 2017')
})
