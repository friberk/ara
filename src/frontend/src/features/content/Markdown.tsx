import 'katex/dist/katex.min.css'
import './markdown.css'
import { useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex, { type Options as KatexOptions } from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { safeUrl } from '@/api/client'
import type { Citation } from '@/api/types'
import { cn } from '@/lib/utils'
import { CitationChip } from './CitationChip'
import { normalizeMath } from './math'
import { remarkCitations } from './remark-citations'

export type MarkdownProps = {
  content: string
  /** Citations of this message or summary. [source:UUID] markers whose UUID is a citation chunk_id become inline chips. */
  citations?: Citation[]
  /** Only citations from this document may render; markers for any other document render nothing. */
  documentId?: string
  /** Called when a reader activates an inline citation chip. */
  onCitation?: (citation: Citation) => void
  className?: string
}

// rehype-katex renders TeX it cannot parse as plain source itself, which is what throwOnError: false asks for.
// No \href or \includegraphics, and no author-sized boxes that could cover the page.
const katexOptions: KatexOptions = { trust: false, maxSize: 20, errorColor: 'var(--muted-foreground)' }
const remarkMathOptions = { singleDollarTextMath: false }

const h3 = 'mt-7 mb-2 text-[1.0625rem] leading-snug font-semibold tracking-[-0.01em] text-balance'
const h4 = 'mt-6 mb-1.5 text-[1em] leading-snug font-semibold text-balance'

// Model output sits under the page's own headings, links leave the app, and nothing loads remote images.
const prose: Components = {
  h1: ({ children }) => <h3 className={h3}>{children}</h3>,
  h2: ({ children }) => <h3 className={h3}>{children}</h3>,
  h3: ({ children }) => <h4 className={h4}>{children}</h4>,
  h4: ({ children }) => <h4 className={h4}>{children}</h4>,
  h5: ({ children }) => <h4 className={h4}>{children}</h4>,
  h6: ({ children }) => <h4 className={h4}>{children}</h4>,
  p: ({ children }) => <p className="my-3.5">{children}</p>,
  a: ({ href, children }) => {
    const url = safeUrl(href)
    return url
      ? <a href={url} target="_blank" rel="noreferrer" className="font-medium underline decoration-foreground/30 underline-offset-[3px] transition-colors hover:decoration-foreground">{children}</a>
      : <span>{children}</span>
  },
  img: () => null,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  ul: ({ className, children }) => <ul className={cn('my-3.5 list-disc space-y-1.5 pl-6 marker:text-muted-foreground', className === 'contains-task-list' && 'list-none pl-1')}>{children}</ul>,
  ol: ({ start, children }) => <ol start={start} className="my-3.5 list-decimal space-y-1.5 pl-6 marker:text-muted-foreground marker:tabular">{children}</ol>,
  li: ({ children }) => <li className="pl-1 [&>ol]:my-1.5 [&>p]:my-1.5 [&>ul]:my-1.5">{children}</li>,
  blockquote: ({ children }) => <blockquote className="my-4 border-l-2 border-border pl-4 text-muted-foreground [&>p]:my-2">{children}</blockquote>,
  hr: () => <hr className="my-7 border-border" />,
  code: ({ className, children }) => <code className={cn('rounded-sm bg-muted px-[0.3em] py-[0.1em] font-mono text-[0.86em]', className)}>{children}</code>,
  pre: ({ children }) => <pre className="my-4 overflow-x-auto rounded-lg bg-muted px-4 py-3 font-mono text-[13px] leading-relaxed [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-[1em]">{children}</pre>,
  table: ({ children }) => <div className="my-4 overflow-x-auto"><table className="w-full border-collapse text-sm tabular">{children}</table></div>,
  th: ({ style, children }) => <th style={style} className="border-b border-border px-3 py-2 text-left align-bottom font-medium whitespace-nowrap">{children}</th>,
  td: ({ style, children }) => <td style={style} className="border-b border-border px-3 py-2 align-top">{children}</td>,
}

/** Safe, readable Markdown for answers and summaries: GFM, KaTeX math and inline page chips for cited passages. */
export function Markdown({ content, citations, documentId, onCitation, className }: MarkdownProps) {
  const sources = useMemo(() => {
    const byChunk = new Map<string, Citation>()
    for (const citation of citations ?? []) {
      const chunkId = citation.chunk_id.toLowerCase()
      if ((!documentId || citation.document_id === documentId) && !byChunk.has(chunkId)) byChunk.set(chunkId, citation)
    }
    return byChunk
  }, [citations, documentId])
  const components = useMemo<Components>(() => ({
    ...prose,
    // remark-citations emits <cite data-chunk-id> only for chunks in `sources`.
    cite: ({ node }) => {
      const chunkId = node?.properties.dataChunkId
      const citation = typeof chunkId === 'string' ? sources.get(chunkId) : undefined
      return citation ? <CitationChip citation={citation} onSelect={onCitation} className="ml-1 align-[0.1em]" /> : null
    },
  }), [sources, onCitation])
  const allowed = useMemo(() => new Map([...sources].map(([chunkId, citation]) => [chunkId, citation.page])), [sources])
  return (
    <div data-slot="markdown" className={cn('content-markdown text-[15.5px] leading-[1.7] wrap-break-word text-foreground [&>:first-child]:mt-0 [&>:last-child]:mb-0', className)}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm, [remarkMath, remarkMathOptions], [remarkCitations, { allowed }]]}
        rehypePlugins={[[rehypeKatex, katexOptions]]}
        components={components}
      >
        {normalizeMath(content)}
      </ReactMarkdown>
    </div>
  )
}
