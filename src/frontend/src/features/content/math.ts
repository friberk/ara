// Models write LaTeX as \( … \) and \[ … \]. Markdown reads those backslashes as escapes and prints "(x)",
// so before parsing we rewrite them to remark-math's $$ syntax. Fenced, indented and inline code, link destinations
// and autolinks are copied verbatim.

/** Blockquote markers, indentation and an optional list marker at the start of a line. */
const container = /^((?:[ \t]*>[ \t]?)*)([ \t]*)((?:[-*+]|\d{1,9}[.)])[ \t]+)?/
const codeFence = /^(?:(?:[ \t]*>[ \t]?)*[ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?)(`{3,}|~{3,})(.*)$/
const listItem = /^[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)/
const blankLine = /\n[ \t]*\n/y
const autolink = /<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*>/y

export function normalizeMath(markdown: string): string {
  if (!markdown.includes('\\(') && !markdown.includes('\\[')) return markdown
  let out = ''
  let i = 0
  let fence: string | null = null
  // Indented code needs a blank line (or the start) before it and cannot be the content of a list item.
  let indented = false
  let afterBlank = true
  let inList = false
  while (i < markdown.length) {
    if (i === 0 || markdown[i - 1] === '\n') {
      const end = lineEnd(markdown, i)
      const line = markdown.slice(i, end)
      if (!fence && line.trim()) {
        const indent = indentColumns(line)
        indented = indent >= 4 && (indented || (afterBlank && !inList))
        if (!indented) inList = listItem.test(line) || (indent > 0 && inList)
        afterBlank = false
        if (indented) {
          out += markdown.slice(i, Math.min(end + 1, markdown.length))
          i = end + 1
          continue
        }
      } else if (!fence) afterBlank = true
      const match = codeFence.exec(line)
      const marker = match?.[1] ?? ''
      const opens = !!match && !(marker.startsWith('`') && match[2]?.includes('`'))
      const closes: boolean = !!match && !!fence && marker[0] === fence[0] && marker.length >= fence.length && match[2]?.trim() === ''
      if (fence || opens) {
        fence = closes ? null : (fence ?? marker)
        out += markdown.slice(i, Math.min(end + 1, markdown.length))
        i = end + 1
        continue
      }
    }
    const char = markdown[i]
    if (char === ']' && markdown[i + 1] === '(') {
      const close = destinationEnd(markdown, i + 2)
      if (close !== -1) {
        out += markdown.slice(i, close + 1)
        i = close + 1
        continue
      }
    }
    if (char === '<') {
      autolink.lastIndex = i
      const link = autolink.exec(markdown)?.[0]
      if (link) {
        out += link
        i += link.length
        continue
      }
    }
    if (char === '`') {
      const run = runLength(markdown, i, '`')
      const close = codeSpanEnd(markdown, i + run, run)
      const next = close === -1 ? i + run : close
      out += markdown.slice(i, next)
      i = next
      continue
    }
    if (char === '\\') {
      const open = markdown[i + 1]
      const end = open === '(' || open === '[' ? mathEnd(markdown, i + 2, open === '(' ? ')' : ']') : -1
      if (end !== -1) {
        const line = out.slice(out.lastIndexOf('\n') + 1)
        const [prefix, rest] = continuation(line)
        const lines = mathLines(markdown.slice(i + 2, end), prefix)
        if (lines.length) {
          i = end + 2
          if (open === '(' || /^(?:\||#{1,6}(?:\s|$))/.test(rest)) {
            out += inlineMath(lines.join(' '))
            continue
          }
          // Display math keeps its lines, so % comments end where the model ended them and aligned rows stay apart.
          const body = lines.join(`\n${prefix}`)
          const fenceText = '$'.repeat(Math.max(2, longestDollarRun(body) + 1))
          out = rest.trim() ? `${out.trimEnd()}\n${prefix}` : out
          out += `${fenceText}\n${prefix}${body}\n${prefix}${fenceText}`
          while (markdown[i] === ' ' || markdown[i] === '\t') i += 1
          if (i < markdown.length && markdown[i] !== '\n') out += `\n${prefix}`
          continue
        }
      }
      // Any other escape, including an escaped backslash, is copied as a pair so "\\(" never opens math.
      out += markdown.slice(i, i + 2)
      i += 2
      continue
    }
    out += char
    i += 1
  }
  return out
}

function lineEnd(text: string, from: number) {
  const end = text.indexOf('\n', from)
  return end === -1 ? text.length : end
}

/** Leading whitespace in columns, with tab stops every four. */
function indentColumns(line: string) {
  let columns = 0
  for (const char of line) {
    if (char === ' ') columns += 1
    else if (char === '\t') columns += 4 - (columns % 4)
    else break
  }
  return columns
}

function runLength(text: string, from: number, char: string) {
  let end = from
  while (text[end] === char) end += 1
  return end - from
}

/** Index after the backtick run that closes a code span, or -1 when the span never closes in its paragraph. */
function codeSpanEnd(text: string, from: number, length: number) {
  for (let j = from; j < text.length; j += 1) {
    blankLine.lastIndex = j
    if (blankLine.test(text)) return -1
    if (text[j] !== '`') continue
    const run = runLength(text, j, '`')
    if (run === length) return j + run
    j += run - 1
  }
  return -1
}

/** Index of the parenthesis that closes a link's destination and title, or -1 when there is none in this paragraph. */
function destinationEnd(text: string, from: number) {
  let depth = 0
  for (let j = from; j < text.length; j += 1) {
    blankLine.lastIndex = j
    if (blankLine.test(text)) return -1
    const char = text[j]
    if (char === '\\') j += 1
    else if (char === '<' && !text.slice(from, j).trim()) j = text.indexOf('>', j)
    else if ((char === '"' || char === "'") && /\s/.test(text[j - 1] ?? '')) j = quoteEnd(text, j + 1, char)
    else if (char === '(') depth += 1
    else if (char === ')') {
      if (depth === 0) return j
      depth -= 1
    }
    if (j === -1) return -1
  }
  return -1
}

/** Index of the quote that closes a link title, or -1. */
function quoteEnd(text: string, from: number, quote: string) {
  for (let j = from; j < text.length; j += 1) {
    if (text[j] === '\\') j += 1
    else if (text[j] === quote) return j
  }
  return -1
}

/** Index of the backslash that closes the math, or -1 when it does not close in this paragraph. */
function mathEnd(text: string, from: number, close: ')' | ']') {
  for (let j = from; j < text.length; j += 1) {
    blankLine.lastIndex = j
    if (blankLine.test(text)) return -1
    if (text[j] !== '\\') continue
    if (text[j + 1] === close) return j
    j += 1
  }
  return -1
}

/** The indentation a block needs to stay inside this line's list item or blockquote, and the line after it. */
function continuation(line: string): [string, string] {
  const match = container.exec(line)
  const [all = '', quotes = '', indent = '', listMarker = ''] = match ?? []
  return [quotes + indent + ' '.repeat(listMarker.length), line.slice(all.length)]
}

/** The math's non-empty lines, trimmed and without the quote markers that wrapped lines carry. */
function mathLines(body: string, prefix: string) {
  const quotes = (prefix.match(/>/g) ?? []).length
  const wrapped = new RegExp(`^(?:[ \\t]*>[ \\t]?){0,${quotes}}`)
  return body.split('\n').map((line, index) => (index ? line.replace(wrapped, '') : line).trim()).filter(Boolean)
}

function longestDollarRun(text: string) {
  return Math.max(0, ...(text.match(/\$+/g) ?? []).map((run) => run.length))
}

function inlineMath(body: string) {
  const fence = '$'.repeat(Math.max(2, longestDollarRun(body) + 1))
  // A dollar against the fence would lengthen it; remark-math strips one padding space on each side.
  return body.startsWith('$') || body.endsWith('$') ? `${fence} ${body} ${fence}` : `${fence}${body}${fence}`
}
