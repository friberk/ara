import type { Parent, PhrasingContent, Root } from 'mdast'
import type { Node } from 'unist'
import { SKIP, visit } from 'unist-util-visit'

// The backend writes [source:<chunk uuid>] after a claim. The pattern (lowercase "source", hex in either case)
// matches the legacy renderer; any other spelling is ordinary text. Leading whitespace goes with the marker, so
// a chip sits against its claim and a dropped marker leaves no gap before the punctuation.
const markerPattern = '\\s*\\[source:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\]'

/**
 * An inline citation. It becomes <cite data-chunk-id data-claim>, which Markdown replaces with a page chip. The claim
 * is the plain text of its paragraph from the previous sentence boundary up to the marker, which the reader uses
 * to mark only the sentences of the cited passage that support it.
 */
export interface CitationMarker extends Node {
  type: 'citationMarker'
  chunkId: string
  data: { hName: 'cite'; hProperties: { dataChunkId: string; dataClaim?: string } }
}

/** The last word before a run of chips, the chips and the punctuation after them, rendered as one nowrap span. */
export interface CitationGroup extends Parent {
  type: 'citationGroup'
  children: PhrasingContent[]
  data: { hName: 'span'; hProperties: { className: string[] } }
}

declare module 'mdast' {
  interface PhrasingContentMap { citationMarker: CitationMarker; citationGroup: CitationGroup }
  interface RootContentMap { citationMarker: CitationMarker; citationGroup: CitationGroup }
}

/** Text with every valid [source:UUID] marker removed, as the reader sees it. */
export function stripCitationMarkers(text: string) {
  return text.replace(new RegExp(markerPattern, 'g'), '')
}

/**
 * The claims in raw answer or summary text that cite any of the given chunks, in order and once each. Each line is
 * read as its own block, without list, heading or quote markers, and a claim ends at its marker as in the rendered
 * text; Markdown emphasis is left in.
 */
export function citingClaims(text: string, chunkIds: ReadonlySet<string>) {
  const claims: string[] = []
  for (const line of text.split('\n')) {
    const marker = new RegExp(markerPattern, 'g')
    const block = line.replace(/^\s*(?:[-*+]|\d+[.)]|#{1,6}|>)\s+/, '')
    let plain = ''
    let cursor = 0
    for (let match = marker.exec(block); match; match = marker.exec(block)) {
      plain += block.slice(cursor, match.index)
      cursor = match.index + match[0].length
      const claim = claimBefore(plain)
      if (chunkIds.has((match[1] ?? '').toLowerCase()) && claim && !claims.includes(claim)) claims.push(claim)
    }
  }
  return claims
}

export type RemarkCitationsOptions = {
  /** Lowercase chunk ids that may render. Markers for any other chunk are removed. */
  allowed: ReadonlySet<string>
}

export function remarkCitations({ allowed }: RemarkCitationsOptions) {
  return (tree: Root) => {
    // A chip is a button and cannot sit inside a link, so markers in link text are only removed.
    visit(tree, ['link', 'linkReference'], (link) => {
      visit(link, 'text', (node) => { node.value = node.value.replace(new RegExp(markerPattern, 'g'), '') })
      return SKIP
    })
    visit(tree, 'text', (node, index, parent) => {
      if (!parent || index === undefined || !node.value.includes('[source:')) return
      const parts = split(node.value, allowed)
      ;(parent.children as PhrasingContent[]).splice(index, 1, ...parts)
      return index + parts.length
    })
    visit(tree, ['paragraph', 'heading', 'tableCell'], (block) => {
      recordClaims(block as Parent)
      return SKIP
    })
    visit(tree, (node) => {
      if (node.type === 'citationGroup') return SKIP
      if ('children' in node) (node as Parent).children = groupWithWord((node as Parent).children as PhrasingContent[])
    })
  }
}

// A sentence ends at . ! or ?, perhaps followed by closing quotes or brackets, and then whitespace.
const sentenceEnd = /[.!?]["'”’)\]]*\s+/g

/** The text since the last sentence boundary: the claim a marker at the end of `text` supports. */
function claimBefore(text: string) {
  const sentence = text.trimEnd()
  let start = 0
  for (const match of sentence.matchAll(sentenceEnd)) start = match.index + match[0].length
  return sentence.slice(start).trim()
}

/** Gives each marker the text since the last sentence boundary of its block; a run of markers shares one claim. */
function recordClaims(block: Parent) {
  let text = ''
  const walk = (parent: Parent) => {
    for (const child of parent.children) {
      if (child.type === 'citationMarker') {
        const claim = claimBefore(text)
        if (claim) child.data.hProperties.dataClaim = claim
      } else if (child.type === 'break') text += ' '
      else if ('value' in child && typeof child.value === 'string' && child.type !== 'html') text += child.value
      else if ('children' in child) walk(child)
    }
  }
  walk(block)
}

/**
 * Wraps the last word before each run of chips, the run and any punctuation right after it in a nowrap span, so a
 * chip never starts a line on its own. A word inside emphasis moves with a copy of that emphasis.
 */
function groupWithWord(children: PhrasingContent[]) {
  const out: PhrasingContent[] = []
  for (let index = 0; index < children.length; index += 1) {
    const child = children[index]!
    const previous = out.at(-1)
    const split = child.type === 'citationMarker' && previous ? lastWord(previous) : null
    if (!split) {
      out.push(child)
      continue
    }
    const group: CitationGroup = { type: 'citationGroup', children: [split.word], data: { hName: 'span', hProperties: { className: ['whitespace-nowrap'] } } }
    out.pop()
    if (split.rest) out.push(split.rest)
    while (children[index]?.type === 'citationMarker') group.children.push(children[index++]!)
    const next = children[index]
    const punctuation = next?.type === 'text' ? /^[^\s\p{L}\p{N}]+/u.exec(next.value)?.[0] : undefined
    if (next?.type === 'text' && punctuation) {
      group.children.push({ type: 'text', value: punctuation })
      const rest = next.value.slice(punctuation.length)
      if (rest) out.push(group, { type: 'text', value: rest })
      else out.push(group)
    } else {
      out.push(group)
      index -= 1
    }
  }
  return out
}

function lastWord(node: PhrasingContent): { rest: PhrasingContent | null; word: PhrasingContent } | null {
  if (node.type === 'text') {
    const word = /\S+$/.exec(node.value)
    if (!word) return null
    const rest = node.value.slice(0, word.index)
    return { rest: rest ? { type: 'text', value: rest } : null, word: { type: 'text', value: word[0] } }
  }
  if (node.type === 'inlineCode' || (node.type as string) === 'inlineMath') return { rest: null, word: node }
  if ((node.type === 'strong' || node.type === 'emphasis' || node.type === 'delete') && node.children.length) {
    const split = lastWord(node.children.at(-1)!)
    if (!split) return null
    const kept = [...node.children.slice(0, -1), ...(split.rest ? [split.rest] : [])]
    return { rest: kept.length ? { ...node, children: kept } as PhrasingContent : null, word: { ...node, children: [split.word] } as PhrasingContent }
  }
  return null
}

function split(value: string, allowed: ReadonlySet<string>) {
  const parts: PhrasingContent[] = []
  const marker = new RegExp(markerPattern, 'g')
  // Markers separated only by whitespace form a run. A run shows each passage once; two passages from one page
  // keep a chip each, since each leads to its own evidence (ARA-075).
  let run = new Set<string>()
  let cursor = 0
  for (let match = marker.exec(value); match; match = marker.exec(value)) {
    const between = value.slice(cursor, match.index)
    if (between) {
      pushText(parts, between)
      run = new Set()
    }
    cursor = match.index + match[0].length
    const chunkId = (match[1] ?? '').toLowerCase()
    if (!allowed.has(chunkId) || run.has(chunkId)) continue
    run.add(chunkId)
    parts.push({ type: 'citationMarker', chunkId, data: { hName: 'cite', hProperties: { dataChunkId: chunkId } } })
  }
  pushText(parts, value.slice(cursor))
  return parts
}

function pushText(parts: PhrasingContent[], value: string) {
  if (!value) return
  const last = parts.at(-1)
  if (last?.type === 'text') last.value += value
  else parts.push({ type: 'text', value })
}
