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

declare module 'mdast' {
  interface PhrasingContentMap { citationMarker: CitationMarker }
  interface RootContentMap { citationMarker: CitationMarker }
}

/** Text with every valid [source:UUID] marker removed, as the reader sees it. */
export function stripCitationMarkers(text: string) {
  return text.replace(new RegExp(markerPattern, 'g'), '')
}

export type RemarkCitationsOptions = {
  /** Page of each lowercase chunk id that may render. Markers for any other chunk are removed. */
  allowed: ReadonlyMap<string, number>
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
  }
}

// A sentence ends at . ! or ?, perhaps followed by closing quotes or brackets, and then whitespace.
const sentenceEnd = /[.!?]["'”’)\]]*\s+/g

/** Gives each marker the text since the last sentence boundary of its block; a run of markers shares one claim. */
function recordClaims(block: Parent) {
  let text = ''
  const walk = (parent: Parent) => {
    for (const child of parent.children) {
      if (child.type === 'citationMarker') {
        const sentence = text.trimEnd()
        let start = 0
        for (const match of sentence.matchAll(sentenceEnd)) start = match.index + match[0].length
        const claim = sentence.slice(start).trim()
        if (claim) child.data.hProperties.dataClaim = claim
      } else if (child.type === 'break') text += ' '
      else if ('value' in child && typeof child.value === 'string' && child.type !== 'html') text += child.value
      else if ('children' in child) walk(child)
    }
  }
  walk(block)
}

function split(value: string, allowed: ReadonlyMap<string, number>) {
  const parts: PhrasingContent[] = []
  const marker = new RegExp(markerPattern, 'g')
  // Markers separated only by whitespace form a run. A run shows each page once, as "p. 6 p. 6" reads as a
  // mistake; the first passage cited on that page stands for it.
  let run = new Set<number>()
  let cursor = 0
  for (let match = marker.exec(value); match; match = marker.exec(value)) {
    const between = value.slice(cursor, match.index)
    if (between) {
      pushText(parts, between)
      run = new Set()
    }
    cursor = match.index + match[0].length
    const chunkId = (match[1] ?? '').toLowerCase()
    const page = allowed.get(chunkId)
    if (page === undefined || run.has(page)) continue
    run.add(page)
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
