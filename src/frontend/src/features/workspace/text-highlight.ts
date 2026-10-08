/**
 * Finds a cited excerpt in a PDF page's text layer (pure; no DOM).
 *
 * The excerpt is a whole stored chunk extracted by PyMuPDF, while the text layer comes from pdf.js, so the
 * two differ in ligatures, hyphenation, whitespace and sometimes block order. Both sides are folded to one
 * comparable form, compared without whitespace, and matched by seed-and-extend: fixed windows of the
 * excerpt are located on the page, grown while the characters agree, and joined across small gaps of
 * extraction noise. Only what lies on this page is returned, so excerpts that overlap it partially still mark
 * their part.
 */

/** One pdf.js text item in reading order; the text layer renders one span per non-empty item. */
export type TextItem = { str: string; hasEOL?: boolean }

const WINDOW = 24
const MIN_SHORT_EXCERPT = 4
const LIGATURES: Record<string, string> = { 'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬅ': 'st', 'ﬆ': 'st', 'æ': 'ae', 'œ': 'oe' }
const LIGATURE = new RegExp(`[${Object.keys(LIGATURES).join('')}]`, 'g')
const LETTER = /\p{L}/u
const WHITESPACE = /\s/

/** Unicode compatibility forms, ligatures, dash and quote variants and case, without touching whitespace. */
function fold(text: string) {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(LIGATURE, (ligature) => LIGATURES[ligature] ?? ligature)
    .replace(/[\u00ad\u200b-\u200d\ufeff]/g, '')
    .replace(/[\u2010-\u2015\u2212]/g, '-')
    .replace(/[\u2018\u2019\u201a\u201b\u2032]/g, "'")
    .replace(/[\u201c\u201d\u201e\u201f\u2033]/g, '"')
}

/** The comparable form of passage text: folded, de-hyphenated across line breaks, whitespace collapsed. */
export function normalizeText(text: string) {
  return fold(text).replace(/(\p{L})-[^\S\n]*\r?\n\s*/gu, '$1').replace(/\s+/g, ' ').trim()
}

/** Where a page character came from in its item's str, or null where folding moved the offsets. */
type Source = readonly [start: number, end: number] | null

/** Page text without whitespace, with the item and the item characters that produced each character. */
function pageKey(items: TextItem[]) {
  const chars: string[] = []
  const owners: number[] = []
  const sources: Source[] = []
  items.forEach((item, index) => {
    // Folding character by character keeps offsets into the item. When that differs from folding the whole item
    // (NFKC composing a combining mark, say), the whole fold is used and this item's offsets are given up.
    const pieces: [text: string, source: Source][] = []
    let at = 0
    for (const point of item.str) {
      pieces.push([fold(point), [at, at + point.length]])
      at += point.length
    }
    const whole = fold(item.str)
    const aligned = pieces.map(([text]) => text).join('') === whole
    for (const [text, source] of aligned ? pieces : [[whole, null] as const]) {
      for (let offset = 0; offset < text.length; offset += 1) {
        const char = text.charAt(offset)
        if (WHITESPACE.test(char)) continue
        chars.push(char)
        owners.push(index)
        sources.push(source)
      }
    }
    // A hyphen that ends a line between letters splits one word, as normalizeText assumes for the excerpt.
    if (item.hasEOL && chars.at(-1) === '-' && LETTER.test(chars.at(-2) ?? '')) { chars.pop(); owners.pop(); sources.pop() }
  })
  return { text: chars.join(''), owners, sources }
}

type Range = [start: number, end: number]
type Anchor = { excerptAt: number; pageAt: number; length: number }

/** Grows a seed while the characters on both sides keep agreeing. */
function extend(anchor: Anchor, excerpt: string, page: string): Anchor {
  let { excerptAt, pageAt, length } = anchor
  while (excerptAt > 0 && pageAt > 0 && excerpt[excerptAt - 1] === page[pageAt - 1]) { excerptAt -= 1; pageAt -= 1; length += 1 }
  while (excerptAt + length < excerpt.length && pageAt + length < page.length && excerpt[excerptAt + length] === page[pageAt + length]) length += 1
  return { excerptAt, pageAt, length }
}

function matchRanges(excerpt: string, page: string): Range[] {
  const whole = page.indexOf(excerpt)
  if (whole >= 0) return excerpt.length >= MIN_SHORT_EXCERPT ? [[whole, whole + excerpt.length]] : []
  if (excerpt.length < WINDOW * 2) return []
  // Windows tile the excerpt; the last one ends at its final character.
  const starts: number[] = []
  for (let at = 0; at + WINDOW <= excerpt.length; at += WINDOW) starts.push(at)
  if (excerpt.length % WINDOW) starts.push(excerpt.length - WINDOW)
  const anchors: Anchor[] = []
  let expected = 0
  for (const excerptAt of starts) {
    const previous = anchors.at(-1)
    if (previous && excerptAt + WINDOW <= previous.excerptAt + previous.length) continue
    const window = excerpt.slice(excerptAt, excerptAt + WINDOW)
    // Prefer the next occurrence in reading order; extraction may also reorder blocks, so fall back to anywhere.
    let pageAt = page.indexOf(window, expected)
    if (pageAt < 0) pageAt = page.indexOf(window)
    if (pageAt < 0) continue
    const anchor = extend({ excerptAt, pageAt, length: WINDOW }, excerpt, page)
    anchors.push(anchor)
    expected = anchor.pageAt + anchor.length
  }
  const matched = anchors.reduce((total, anchor) => total + anchor.length, 0)
  if (matched < WINDOW * 2) return []
  const ranges: Range[] = anchors.map((anchor) => [anchor.pageAt, anchor.pageAt + anchor.length])
  // Neighbouring anchors in the same order on both sides belong to one passage; bridge the noise between them.
  for (let index = 1; index < anchors.length; index += 1) {
    const before = anchors[index - 1]!
    const after = anchors[index]!
    const pageGap = after.pageAt - (before.pageAt + before.length)
    const excerptGap = Math.max(0, after.excerptAt - (before.excerptAt + before.length))
    if (pageGap > 0 && pageGap <= excerptGap * 1.5 + 16) ranges.push([before.pageAt + before.length, after.pageAt])
  }
  return ranges
}

function locate(items: TextItem[], excerpt: string) {
  const page = pageKey(items)
  const key = normalizeText(excerpt).replace(/\s/g, '')
  return { page, ranges: key && page.text ? matchRanges(key, page.text) : [] }
}

/** Whitespace-only items between marked items are part of the passage too, so the mark reads as one run. */
function withGaps(items: TextItem[], indexes: number[]) {
  const filled: number[] = []
  for (const index of indexes) {
    const last = filled.at(-1)
    const between = last === undefined ? [] : Array.from({ length: index - last - 1 }, (_, offset) => last + 1 + offset)
    if (between.every((item) => !items[item]!.str.trim())) filled.push(...between)
    filled.push(index)
  }
  return filled
}

/**
 * Indexes of the text items that the excerpt covers on this page, in order. An empty result means the
 * passage could not be located reliably, so the caller should fall back to showing the page.
 */
export function findExcerptItems(items: TextItem[], excerpt: string): number[] {
  const { page, ranges } = locate(items, excerpt)
  const covered = new Set<number>()
  for (const [start, end] of ranges) for (let at = start; at < end; at += 1) covered.add(page.owners[at]!)
  return withGaps(items, [...covered].sort((a, b) => a - b))
}

/** Characters [start, end) of one text item's str. */
export type TextRange = { item: number; start: number; end: number }

/**
 * The characters of each text item that the excerpt covers, so a passage that begins or ends mid-line is marked
 * from its first character to its last. An item whose offsets folding moved is covered whole.
 */
export function findExcerptRanges(items: TextItem[], excerpt: string): TextRange[] {
  const { page, ranges } = locate(items, excerpt)
  const extents = new Map<number, [start: number, end: number]>()
  for (const [start, end] of ranges) {
    for (let at = start; at < end; at += 1) {
      const item = page.owners[at]!
      const [from, to] = page.sources[at] ?? [0, items[item]!.str.length]
      const extent = extents.get(item)
      extents.set(item, extent ? [Math.min(extent[0], from), Math.max(extent[1], to)] : [from, to])
    }
  }
  return withGaps(items, [...extents.keys()].sort((a, b) => a - b)).map((item) => {
    const [start, end] = extents.get(item) ?? [0, items[item]!.str.length]
    return { item, start, end }
  })
}
