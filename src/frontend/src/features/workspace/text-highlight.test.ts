import { findExcerptItems, normalizeText, type TextItem } from './text-highlight'

/** One pdf.js text item per printed line, as the text layer renders a simple single-column page. */
const lines = (...rows: string[]): TextItem[] => rows.map((str) => ({ str, hasEOL: true }))
const page = lines(
  'Attention Is All You Need',
  'Abstract',
  'The dominant sequence transduction models are based on complex',
  'recurrent or convolutional neural networks that include an encoder',
  'and a decoder. The best performing models also connect the encoder',
  'and decoder through an attention mechanism. We propose a new simple',
  'network architecture, the Transformer, based solely on attention',
  'mechanisms, dispensing with recurrence and convolutions entirely.',
)

describe('normalizeText', () => {
  test('Given ligatures, mixed case and ragged whitespace, Then text folds to one comparable form', () => {
    expect(normalizeText('The ﬁrst  Eﬃcient\n\tMODEL')).toBe('the first efficient model')
  })

  test('Given a word hyphenated across a line break, Then the halves are joined', () => {
    expect(normalizeText('retrieval-aug-\nmented gen-\r\n  eration')).toBe('retrieval-augmented generation')
  })
})

describe('findExcerptItems', () => {
  test('Given the excerpt is on the page, Then exactly the items it covers are returned', () => {
    expect(findExcerptItems(page, 'The dominant sequence transduction models are based on complex\nrecurrent or convolutional neural networks that include an encoder')).toEqual([2, 3])
  })

  test('Given ligature glyphs in the text layer, When the excerpt uses plain letters, Then the items still match', () => {
    const items = lines('We train eﬃcient models on the ﬁrst ﬂoor of the', 'benchmark and report the ﬁnal scores below.')
    expect(findExcerptItems(items, 'We train efficient models on the first floor of the benchmark and report the final scores below.')).toEqual([0, 1])
  })

  test('Given a word hyphenated at a line end, Then the excerpt matches with or without the hyphen break', () => {
    const items = lines('The retrieval-first assistant is evaluated with aug-', 'mented passages drawn from twelve synthetic examples.')
    expect(findExcerptItems(items, 'retrieval-first assistant is evaluated with aug-\nmented passages drawn from twelve')).toEqual([0, 1])
    expect(findExcerptItems(items, 'retrieval-first assistant is evaluated with augmented passages drawn from twelve')).toEqual([0, 1])
  })

  test('Given text split into words and spaces, When the excerpt wraps differently, Then whitespace does not matter', () => {
    const items: TextItem[] = [
      { str: 'Source' }, { str: ' ' }, { str: 'citations make' }, { str: ' ' }, { str: 'the output', hasEOL: true },
      { str: 'easier  to inspect.' }, { str: ' ' }, { str: 'This is a synthetic fixture.', hasEOL: true },
    ]
    expect(findExcerptItems(items, 'source citations\n\nmake the   output easier to\ninspect.')).toEqual([0, 1, 2, 3, 4, 5])
  })

  test('Given an excerpt that begins on the previous page, Then only the part on this page is marked', () => {
    const excerpt = 'Earlier work on statistical machine translation relied on phrase tables and alignment models.\n' + 'Attention Is All You Need\nAbstract\nThe dominant sequence transduction models are based on complex'
    expect(findExcerptItems(page, excerpt)).toEqual([0, 1, 2])
  })

  test('Given an excerpt that continues past this page, Then only the part on this page is marked', () => {
    const excerpt = 'network architecture, the Transformer, based solely on attention\nmechanisms, dispensing with recurrence and convolutions entirely.\n' + '1 Introduction\nRecurrent neural networks, long short-term memory and gated recurrent networks'
    expect(findExcerptItems(page, excerpt)).toEqual([6, 7])
  })

  test('Given small extraction differences inside the passage, Then the passage is still marked as one run', () => {
    const excerpt = 'and a decoder. The best performing models also connect the encoder\nand decoder through an atention mechanism. We propose a new simple'
    expect(findExcerptItems(page, excerpt)).toEqual([4, 5])
  })

  test('Given a passage that is not on this page, Then nothing is marked', () => {
    expect(findExcerptItems(page, 'The measured answer accuracy in this synthetic experiment is 86 percent.')).toEqual([])
    expect(findExcerptItems(page, '')).toEqual([])
    expect(findExcerptItems([], 'Attention Is All You Need')).toEqual([])
  })

  test('Given a short excerpt, Then it must appear whole', () => {
    expect(findExcerptItems(page, 'Abstract')).toEqual([1])
    expect(findExcerptItems(page, 'Abstraction')).toEqual([])
  })
})
