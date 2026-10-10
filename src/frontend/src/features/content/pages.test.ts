// How a citation chip names its page and, in a chat over several papers, its paper (ARA-110).
import { pageLabel, sourceLabel, sourceName } from './pages'

const page2 = { page: 2, page_end: null }

test('Given a single-paper chat, Then a chip reads "p. 2"', () => {
  expect(sourceLabel(page2)).toBe('p. 2')
  expect(pageLabel({ page: 5, page_end: 6 })).toBe('p. 5–6')
})

test('Given a paper in a multi-paper chat, Then the chip reads author, year and page joined by commas, never a middle dot', () => {
  expect(sourceLabel(page2, 'Han et al., 2018')).toBe('Han et al., 2018, p. 2')
  expect(sourceLabel({ page: 5, page_end: 6 }, 'Han, n.d.')).toBe('Han, n.d., p. 5–6')
  expect(sourceLabel(page2, 'Han et al., 2018')).not.toContain('·')
})

test('Given a paper in a multi-paper chat, Then the chip names the paper, then the page', () => {
  expect(sourceName({ page: 2, page_end: null, section: null }, 'Han et al., 2018')).toBe('Source, Han et al., 2018, page 2')
})
