import { authorShort, citationLine, mentionLabel, mentionName, shortCitation, shortPaperName } from './paper-names'

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

test('Given a paper, Then its mention pill is labelled with its title, cut only when very long, or its short name without one', () => {
  expect(mentionLabel(paper(['Ashish Vaswani'], 2017))).toBe('Attention Is All You Need')
  expect(mentionLabel({ title: '  ', authors: ['Ashish Vaswani'], year: 2017 })).toBe('Vaswani 2017')
  const long = mentionLabel({ title: 'Word '.repeat(80), authors: [], year: null })
  expect(long.length).toBeLessThanOrEqual(300)
  expect(long).toMatch(/Word…$/)
})

test('Given what a paper has, Then its short citation is plain text as PaperCitation sets it, and empty without parts', () => {
  expect(shortCitation(paper(['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'], 2017, 'NeurIPS'))).toBe('Vaswani et al. (2017), NeurIPS')
  expect(shortCitation(paper(['Ashish Vaswani'], 2017))).toBe('Vaswani (2017)')
  expect(shortCitation(paper(['Ashish Vaswani'], null, 'NeurIPS'))).toBe('Vaswani, NeurIPS')
  expect(shortCitation(paper([], 2017, 'NeurIPS'))).toBe('2017, NeurIPS')
  expect(shortCitation(paper([], null, 'NeurIPS'))).toBe('NeurIPS')
  expect(shortCitation(paper([]))).toBe('')
})
