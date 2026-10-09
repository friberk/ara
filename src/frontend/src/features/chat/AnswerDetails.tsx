import { useId } from 'react'
import type { ContextUsage, RetrievalSummary } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover'

const count = (value: number) => value.toLocaleString('en-US')

/**
 * "How this answer was found": the search the answer was grounded in and how much of the model's context it used,
 * in plain words. Only answers saved with retrieval details have one.
 */
export function AnswerDetails({ retrieval, context, model }: { retrieval: RetrievalSummary; context?: ContextUsage | null; model: string | null }) {
  const { models } = useGenerationSettings()
  const titleId = useId()
  const query = retrieval.standalone_query || retrieval.search_queries?.[0]
  const modelName = models.find((item) => item.key === model)?.display_name
  const rows = [
    query && `Searched for “${query}”`,
    `${retrieval.mode === 'hybrid' ? 'Keyword and meaning search' : 'Keyword search'}${retrieval.note ? `. ${retrieval.note}` : ''}`,
    retrieval.reranked ? 'Results were reranked' : 'Results were not reranked',
    `Used ${count(retrieval.passages_used)} of ${count(retrieval.passages_found)} relevant passages${retrieval.limited_by_context ? ` (limited by ${modelName ? `${modelName}’s` : 'the model’s'} context)` : ''}`,
    context && `Context: ${count(context.input_tokens)} of ${count(context.input_budget ?? context.window)} tokens${context.summary_version ? ' (earlier messages summarized)' : ''}`,
  ].filter((row): row is string => !!row)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="ghost" size="xs" className="-mx-1 font-normal text-muted-foreground hover:text-foreground">Details</Button>
      </PopoverTrigger>
      <PopoverContent align="start" aria-labelledby={titleId} className="w-80 max-w-[calc(100vw-1.5rem)] gap-2 p-3">
        <PopoverHeader><PopoverTitle id={titleId}>How this answer was found</PopoverTitle></PopoverHeader>
        <ul className="grid gap-1.5 text-[13px] leading-relaxed text-pretty text-muted-foreground tabular">
          {rows.map((row) => <li key={row}>{row}</li>)}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
