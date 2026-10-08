import { authorLine, displayText, doiLink, otherProvider, recordLink } from './paper-format'

test('Given provider text with control or private-use characters, Then display text drops them and collapses spaces', () => {
  expect(displayText('Xin Du')).toBe('Xin Du')
  expect(displayText('Regex\u0007 denial\u0000of   service\n')).toBe('Regex denial of service')
  expect(displayText(null)).toBe('')
  // Letters outside ASCII are content, not noise.
  expect(displayText('Łukasz Kaiser')).toBe('Łukasz Kaiser')
})

test('Given more than three authors, Then the line keeps three and a non-breaking et al. with the full list beside it', () => {
  const line = authorLine(['Ada Lovelace', 'Alan Turing', 'Grace Hopper', 'Edsger Dijkstra'])
  expect(line).toEqual({ short: 'Ada Lovelace, Alan Turing, Grace Hopper et al.', full: 'Ada Lovelace, Alan Turing, Grace Hopper, Edsger Dijkstra', truncated: true })
  expect(authorLine(['Ada Lovelace', ' ', 'Alan Turing'])).toEqual({ short: 'Ada Lovelace, Alan Turing', full: 'Ada Lovelace, Alan Turing', truncated: false })
  expect(authorLine([])).toBeNull()
  expect(authorLine(undefined)).toBeNull()
})

test('Given DOIs in several spellings, Then each resolves through doi.org', () => {
  expect(doiLink('10.1234/abc')).toEqual({ doi: '10.1234/abc', href: 'https://doi.org/10.1234/abc' })
  expect(doiLink('https://doi.org/10.1234/abc')).toEqual({ doi: '10.1234/abc', href: 'https://doi.org/10.1234/abc' })
  expect(doiLink('doi: 10.1234/abc')?.doi).toBe('10.1234/abc')
  expect(doiLink('  ')).toBeNull()
  expect(doiLink(null)).toBeNull()
})

test('Given record links, Then they are named by site, unsafe or duplicate DOI links are dropped', () => {
  expect(recordLink('https://www.semanticscholar.org/paper/abc')).toEqual({ href: 'https://www.semanticscholar.org/paper/abc', label: 'Semantic Scholar' })
  expect(recordLink('https://openalex.org/W1')?.label).toBe('OpenAlex')
  expect(recordLink('https://arxiv.org/abs/1706.03762')?.label).toBe('arXiv')
  expect(recordLink('https://dl.acm.org/doi/10.1145/1')?.label).toBe('dl.acm.org')
  expect(recordLink('https://doi.org/10.1234/ABC', 'https://doi.org/10.1234/abc')).toBeNull()
  expect(recordLink('javascript:alert(1)')).toBeNull()
  expect(otherProvider('openalex')).toBe('semantic_scholar')
  expect(otherProvider('semantic_scholar')).toBe('openalex')
})
