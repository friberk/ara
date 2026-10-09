import { useId } from 'react'
import type { ChatMemory } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover'
import { Markdown } from '@/features/content'

/**
 * The composer footnote once a chat's earlier messages are summarized, with the summary on request. It names the chat
 * model selected in the composer, whose context the conversation must fit, not memory.model, which wrote the summary.
 * The summary is shown as plain Markdown: it has no citations of its own, so any source markers in it render nothing.
 */
export function MemoryNote({ memory }: { memory: ChatMemory }) {
  const model = useGenerationSettings().selectedModel?.display_name
  const titleId = useId()
  return (
    <span>
      {model ? `Earlier messages are summarized to fit ${model}.` : 'Earlier messages are summarized to fit the model’s context.'}{' '}
      <Popover>
        <PopoverTrigger className="cursor-pointer text-foreground underline decoration-foreground/25 underline-offset-2 outline-none hover:decoration-foreground focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring">View summary</PopoverTrigger>
        <PopoverContent side="top" aria-labelledby={titleId} className="w-[min(28rem,calc(100vw-2rem))] gap-2 p-3 text-left">
          <PopoverHeader>
            <PopoverTitle id={titleId}>Conversation summary</PopoverTitle>
            <PopoverDescription className="text-xs tabular">Covers the first {memory.summarized_messages} messages. The messages themselves are unchanged.</PopoverDescription>
          </PopoverHeader>
          <div className="max-h-[min(55vh,26rem)] overflow-y-auto">
            <Markdown content={memory.summary} className="text-sm leading-relaxed" />
          </div>
        </PopoverContent>
      </Popover>
    </span>
  )
}
