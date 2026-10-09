/**
 * The plain text of a stored passage (pure; no DOM).
 *
 * Chunks are PyMuPDF4LLM layout Markdown, while a PDF's text layer and a clamped preview are plain text. The passage
 * is parsed as GFM with the parser react-markdown uses, and only its words are kept: blocks are separated by a blank
 * line, list items and table rows by a line break, and table cells by a space. HTML tags such as <sup> are dropped
 * and their text kept. Ordered items keep their numbers, which the page prints; bullets are dropped.
 */
import type { Nodes } from 'mdast'
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmFromMarkdown } from 'mdast-util-gfm'
import { gfm } from 'micromark-extension-gfm'

function inline(node: Nodes): string {
  if (node.type === 'html') return ''
  if (node.type === 'break') return '\n'
  if (node.type === 'image') return node.alt ?? ''
  if ('value' in node) return node.value
  return 'children' in node ? node.children.map(inline).join('') : ''
}

function block(node: Nodes): string {
  switch (node.type) {
    case 'root':
    case 'blockquote':
      return node.children.map(block).filter(Boolean).join('\n\n')
    case 'list':
      return node.children.map((item, index) => (node.ordered ? `${(node.start ?? 1) + index}. ` : '') + block(item)).join('\n')
    case 'listItem':
      return node.children.map(block).filter(Boolean).join('\n')
    case 'table':
      return node.children.map(block).join('\n')
    case 'tableRow':
      return node.children.map(block).join(' ')
    case 'thematicBreak':
      return ''
    default:
      return inline(node)
  }
}

export function markdownToText(markdown: string): string {
  return block(fromMarkdown(markdown, { extensions: [gfm()], mdastExtensions: [gfmFromMarkdown()] })).trim()
}
