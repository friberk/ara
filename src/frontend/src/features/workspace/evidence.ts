/**
 * Chooses the part of a cited excerpt that supports one claim (pure; no DOM).
 *
 * A stored chunk is a few thousand characters and can run across several sections, while the claim that cites it is
 * one sentence of the answer. Each sentence of the excerpt is scored by the content words it shares with the claim,
 * each word weighted by how rare it is among the excerpt's sentences, so a topic word that recurs everywhere counts
 * for little. Words are compared after folding case and ligatures, dropping stopwords and punctuation and stripping
 * common suffixes; two stems also match when one is a longer word's prefix.
 */
import { findExcerptItems, findExcerptRanges, normalizeText, type TextItem, type TextRange } from './text-highlight'

const MAX_SENTENCES = 3
/** A further sentence must score at least this share of the best one. */
const FURTHER_SHARE = 0.5
/** The best sentence must share at least this many distinct content words with the claim. */
const MIN_SHARED_WORDS = 2
const MIN_PREFIX = 5

// Function words, plus the reporting verbs answers use to frame a claim ("the paper describes …"), which say
// nothing about the evidence itself.
const STOPWORDS = new Set(`
  a about above after again against all also am an and any are as at be because been before being below between both
  but by can could did do does doing down during each few for from further had has have having he her here hers him
  his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours out
  over own same she should so some such than that the their theirs them then there these they this those through to
  too under until up very was we were what when where which while who whom why will with would you your
  may might must shall upon via within without yet thus hence however therefore whereas
  paper study work author authors report reports reported describe describes described present presents presented
  show shows shown showed introduce introduces introduced propose proposes proposed discuss discusses discussed
`.trim().split(/\s+/))

/** A word (letters) or a number such as 2014, 28.4 or 100,000. */
const TOKEN = /\p{L}[\p{L}\p{M}]*|\p{N}+(?:[.,]\p{N}+)*/gu
const NUMBER = /^\p{N}/u
/** Paragraph breaks, and sentence ends followed by whitespace and a capital, digit or opening mark. */
const BOUNDARY = /\n[^\S\n]*\n\s*|(?<=[.!?]["'”’)\]]*)\s+(?=[\p{Lu}\p{N}"“'‘([])/gu

function stem(word: string) {
  if (NUMBER.test(word)) return word
  let stemmed = word
  if (/ies$/.test(stemmed) && stemmed.length > 4) stemmed = `${stemmed.slice(0, -3)}y`
  else if (/[^siu]s$/.test(stemmed) && stemmed.length > 3) stemmed = stemmed.slice(0, -1)
  if (/ied$/.test(stemmed) && stemmed.length > 4) stemmed = `${stemmed.slice(0, -3)}y`
  else if (/ed$/.test(stemmed) && stemmed.length > 5) stemmed = stemmed.slice(0, -2)
  else if (/ing$/.test(stemmed) && stemmed.length > 6) stemmed = stemmed.slice(0, -3)
  else if (/ly$/.test(stemmed) && stemmed.length > 5) stemmed = stemmed.slice(0, -2)
  return stemmed
}

function contentWords(text: string) {
  const words = new Set<string>()
  for (const [token] of normalizeText(text).matchAll(TOKEN)) {
    if (STOPWORDS.has(token) || token.length < (NUMBER.test(token) ? 2 : 3)) continue
    words.add(stem(token))
  }
  return words
}

function sameWord(a: string, b: string) {
  if (a === b) return true
  const [short, long] = a.length < b.length ? [a, b] : [b, a]
  return short.length >= MIN_PREFIX && !NUMBER.test(short) && long.startsWith(short)
}

/** The excerpt's sentences, verbatim and in order, so each can be located in the text layer like the excerpt. */
function sentences(excerpt: string) {
  const found: string[] = []
  let start = 0
  for (const match of excerpt.matchAll(BOUNDARY)) {
    found.push(excerpt.slice(start, match.index).trim())
    start = match.index + match[0].length
  }
  found.push(excerpt.slice(start).trim())
  return found.filter(Boolean)
}

/**
 * The 1–3 sentences of the excerpt that best support the claim, verbatim and in excerpt order. Further sentences
 * must score at least half the best; neighbours of the chosen ones are taken first so the passage stays contiguous.
 * An empty result means no sentence clearly supports the claim, so the caller should mark the whole excerpt.
 */
export function selectEvidence(excerpt: string, claim: string): string[] {
  const claimWords = [...contentWords(claim)]
  const candidates = sentences(excerpt).map((text) => ({ text, words: [...contentWords(text)] }))
  if (!claimWords.length || !candidates.length) return []
  const shared = candidates.map(({ words }) => claimWords.filter((word) => words.some((other) => sameWord(word, other))))
  const weight = new Map(claimWords.map((word) => {
    const sentencesWithWord = shared.filter((words) => words.includes(word)).length
    return [word, Math.log(1 + candidates.length / Math.max(1, sentencesWithWord))]
  }))
  const scores = shared.map((words) => words.reduce((total, word) => total + (weight.get(word) ?? 0), 0))
  const best = scores.reduce((top, score, index) => (score > scores[top]! ? index : top), 0)
  if (shared[best]!.length < MIN_SHARED_WORDS) return []
  const chosen = new Set([best])
  const bar = scores[best]! * FURTHER_SHARE
  while (chosen.size < MAX_SENTENCES) {
    const qualifying = scores.flatMap((score, index) => (!chosen.has(index) && score > 0 && score >= bar ? [index] : []))
    if (!qualifying.length) break
    const adjacent = qualifying.filter((index) => chosen.has(index - 1) || chosen.has(index + 1))
    const pool = adjacent.length ? adjacent : qualifying
    chosen.add(pool.reduce((top, index) => (scores[index]! > scores[top]! ? index : top)))
  }
  return [...chosen].sort((a, b) => a - b).map((index) => candidates[index]!.text)
}

export type Evidence = { strong: TextRange[]; context: number[] }

/**
 * What to mark for a citation: the characters of the sentences that support the claim are strong, and the other
 * text items of the excerpt on this page are context. Without a claim, or when no sentence supports it or none can
 * be located in the text layer, the whole excerpt is strong as before. Both lists are empty when the passage is not
 * on this page.
 */
export function findEvidence(items: TextItem[], excerpt: string, claim?: string): Evidence {
  const located = new Map<number, TextRange>()
  for (const sentence of claim ? selectEvidence(excerpt, claim) : []) {
    for (const range of findExcerptRanges(items, sentence)) {
      const known = located.get(range.item)
      located.set(range.item, known ? { item: range.item, start: Math.min(known.start, range.start), end: Math.max(known.end, range.end) } : range)
    }
  }
  if (!located.size) return { strong: findExcerptRanges(items, excerpt), context: [] }
  return {
    strong: [...located.values()].sort((a, b) => a.item - b.item),
    context: findExcerptItems(items, excerpt).filter((index) => !located.has(index)),
  }
}
