import type { PhrasingContent, Root } from 'mdast'
import type { Node } from 'unist'
import { SKIP, visit } from 'unist-util-visit'

// The backend writes [source:<chunk uuid>] after a claim. The pattern (lowercase "source", hex in either case)
// matches the legacy renderer; any other spelling is ordinary text. Leading whitespace goes with the marker, so
// a chip sits against its claim and a dropped marker leaves no gap before the punctuation.
const markerPattern = '\\s*\\[source:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\]'

/** An inline citation. It becomes <cite data-chunk-id>, which Markdown replaces with a page chip. */
export interface CitationMarker extends Node {
  type: 'citationMarker'
  chunkId: string
  data: { hName: 'cite'; hProperties: { dataChunkId: string } }
}

declare module 'mdast' {
  interface PhrasingContentMap { citationMarker: CitationMarker }
  interface RootContentMap { citationMarker: CitationMarker }
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
  }
}

function split(value: string, allowed: ReadonlySet<string>) {
  const parts: PhrasingContent[] = []
  const marker = new RegExp(markerPattern, 'g')
  // Markers separated only by whitespace form a run; a chunk cited twice in one run shows once.
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
