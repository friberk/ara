import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import type { Citation, Message } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Markdown, pageLabel, SourceList } from '@/features/content'
import { GenerationMeta } from '@/features/summary'
import { useOptionalWorkspace } from '@/features/workspace/workspace-context'
import { AnswerDetails } from './AnswerDetails'
import type { ChatSources } from './chat-sources'

const sourceMarker = /\s?\[source:([0-9a-fA-F-]{36})\]/g
/** Copied answers keep their evidence as readable page references instead of transport markers. */
function plainAnswer(content: string, citations: Citation[], paperName?: (citation: Citation) => string | undefined) {
  return content.replace(sourceMarker, (_marker, chunkId: string) => {
    const citation = citations.find((item) => item.chunk_id === chunkId)
    const paper = citation && paperName?.(citation)
    return citation ? ` (${paper ? `${paper}, ` : ''}${pageLabel(citation)})` : ''
  })
}

export function UserMessage({ content }: { content: string }) {
  return (
    <article aria-label="Your message" className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 text-[15.5px] leading-7 break-words whitespace-pre-wrap">{content}</div>
    </article>
  )
}

function Preparing() {
  return <p className="text-[15.5px] leading-7 text-muted-foreground motion-safe:animate-pulse">Preparing a response…</p>
}

/** Placeholder before the server has started the answer. */
export function PendingAnswer() {
  return <article aria-label="Assistant message" aria-busy="true"><Preparing /></article>
}

function CopyAnswer({ message, paperName }: { message: Message; paperName?: (citation: Citation) => string | undefined }) {
  const [copied, setCopied] = useState<'copied' | 'failed' | null>(null)
  async function copy() {
    try {
      await navigator.clipboard.writeText(plainAnswer(message.content, message.citations, paperName))
      setCopied('copied')
    } catch {
      setCopied('failed')
    }
    window.setTimeout(() => setCopied(null), 2000)
  }
  const label = copied === 'copied' ? 'Copied' : copied === 'failed' ? 'Could not copy. Select the text instead.' : 'Copy answer'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button type="button" variant="ghost" size="icon-xs" aria-label={label} onClick={() => void copy()} className="-ml-1 text-muted-foreground hover:text-foreground">
          {copied === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

/**
 * An answer as prose without a bubble. Citation chips go to the workspace reader when there is one;
 * elsewhere the content module's source dialog applies. The footer names the model the answer was
 * generated with, as stored, never the current selection.
 */
export function AssistantMessage({ message, sources, progress }: { message: Message; sources: ChatSources; progress?: string | null }) {
  const workspace = useOptionalWorkspace()
  const { documents, paperName, withPaper } = sources
  const showSource = workspace ? (citation: Citation, claim?: string) => workspace.showSource(withPaper(citation), claim) : undefined
  const writing = message.state === 'processing'
  return (
    // One minmax(0, 1fr) column: an implicit grid track would grow to the widest link, identifier, table or code block
    // and push the whole answer past a narrow screen (ARA-097); now they wrap or scroll inside the answer.
    <article aria-label="Assistant message" aria-busy={writing} className="grid grid-cols-1 gap-2.5">
      {writing && progress && <p className="text-sm leading-7 text-muted-foreground motion-safe:animate-pulse">{progress}</p>}
      {writing && !message.content ? !progress && <Preparing /> : message.content ? (
        <div className="text-[15.5px] leading-7">
          <Markdown content={message.content} citations={message.citations} documents={documents} paperName={paperName} onCitation={showSource} />
          {writing && <span aria-hidden="true" className="mt-2 block size-2.5 rounded-full bg-foreground motion-safe:animate-pulse" />}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No answer was saved.</p>
      )}
      {!writing && message.grounding === 'insufficient' && <p className="text-sm text-muted-foreground">The paper doesn’t contain enough evidence for this.</p>}
      {message.citations.length > 0 && <SourceList citations={message.citations} documents={documents} paperName={paperName} context={message.content} onSelect={showSource} className="flex flex-wrap gap-1.5" />}
      {!writing && (
        <div className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {message.content && <CopyAnswer message={message} paperName={paperName} />}
          <GenerationMeta model={message.model} effort={message.reasoning_effort} />
          {message.retrieval && <AnswerDetails retrieval={message.retrieval} context={message.context} model={message.model} />}
          {message.state === 'interrupted' && <Badge variant="secondary" className="bg-warning-muted font-normal text-warning">Interrupted</Badge>}
          {message.state === 'failed' && <Badge variant="destructive" className="font-normal">Failed</Badge>}
        </div>
      )}
    </article>
  )
}
