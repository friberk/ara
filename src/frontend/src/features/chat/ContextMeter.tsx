import { useId, useRef, useState } from 'react'
import type { GenerationSettings } from '@/api/types'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { useChatUsage } from '@/hooks/queries/usage'
import { cn } from '@/lib/utils'
import { formatTokens, formatUsd, usedShare } from '@/lib/usage-format'

const RADIUS = 7
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

type SpendKind = 'answers' | 'planning' | 'compaction' | 'embeddings' | 'reranking'

/** Spend by kind, in the order a question incurs it; free kinds are not listed. */
const lines: [SpendKind, string][] = [['answers', 'Answers'], ['planning', 'Follow-up planning'], ['compaction', 'Conversation summaries'], ['embeddings', 'Query embeddings'], ['reranking', 'Reranking']]

/**
 * A hollow ring at the bottom left of the composer: how much of the selected model's input budget the latest answer
 * used, and what the chat has cost. Hover or keyboard focus shows the numbers; a tap or click keeps them open.
 * The server prices recorded calls only, so the card says when earlier answers were not tracked.
 */
export function ContextMeter({ chatId, settings }: { chatId: string; settings: GenerationSettings }) {
  const usage = useChatUsage(chatId, settings)
  const [open, setOpen] = useState(false)
  const pinned = useRef(false)
  const pointer = useRef(false)
  const button = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const data = usage.data
  if (!data) return null

  const { context, cost } = data
  const { percent, fraction } = usedShare(context.used_tokens, context.input_budget)
  const free = cost.local && !(Number(cost.total) > 0)
  const spend = free ? 'Local model, $0.00' : `${formatUsd(cost.total)} this chat`
  const close = () => { pinned.current = false; setOpen(false) }
  const visible = lines.filter(([key]) => Number(cost[key]) > 0)

  return (
    <Popover open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <PopoverAnchor asChild>
        <button
          ref={button}
          type="button"
          aria-label={`Context ${percent}% used of ${formatTokens(context.input_budget)} tokens. ${spend}.`}
          aria-haspopup="dialog"
          aria-expanded={open}
          onPointerDown={() => { pointer.current = true }}
          onPointerEnter={(event) => { if (event.pointerType !== 'touch') setOpen(true) }}
          onPointerLeave={(event) => { if (event.pointerType !== 'touch' && !pinned.current) setOpen(false) }}
          onFocus={() => { if (!pointer.current) setOpen(true) }}
          onBlur={() => { pointer.current = false; if (!pinned.current) setOpen(false) }}
          onClick={() => { pointer.current = false; if (pinned.current) close(); else { pinned.current = true; setOpen(true) } }}
          className={cn('inline-flex size-8 cursor-pointer items-center justify-center rounded-full text-muted-foreground outline-none transition-[color,background-color,opacity] hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[stale=true]:opacity-60', open && 'bg-accent text-foreground')}
          data-stale={usage.isPlaceholderData}
        >
          <svg viewBox="0 0 20 20" className="size-5 -rotate-90" fill="none" strokeWidth="2.5" aria-hidden="true">
            <circle cx="10" cy="10" r={RADIUS} stroke="currentColor" className="opacity-25" />
            <circle
              cx="10" cy="10" r={RADIUS}
              stroke="currentColor" strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE} strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
              data-fraction={fraction}
              className={cn('transition-[stroke-dashoffset] duration-500 motion-reduce:transition-none', percent >= 90 ? 'text-destructive' : 'text-foreground')}
              style={{ opacity: fraction ? 1 : 0 }}
            />
          </svg>
        </button>
      </PopoverAnchor>
      <PopoverContent
        side="top" align="start" sideOffset={6}
        aria-labelledby={titleId}
        className="w-64 gap-2.5 p-3 text-left tabular"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
        onInteractOutside={(event) => { if (button.current?.contains(event.target as Node)) event.preventDefault() }}
      >
        <p id={titleId} className="sr-only">Context and cost</p>
        <div className="grid gap-0.5">
          <span className="text-xs text-muted-foreground">Context</span>
          <span className="font-medium">{formatTokens(context.used_tokens ?? 0)} / {formatTokens(context.input_budget)} tokens · {percent}%</span>
          {context.window !== context.input_budget && <span className="text-xs text-muted-foreground">Model window {formatTokens(context.window)} tokens</span>}
        </div>
        <div className="grid gap-1 border-t pt-2.5">
          <span className="font-medium">{free ? 'Local model · $0.00' : `${formatUsd(cost.total)} this chat`}</span>
          {!free && visible.map(([key, label]) => (
            <div key={key} className="flex justify-between gap-3 text-xs text-muted-foreground"><span>{label}</span><span>{formatUsd(cost[key])}</span></div>
          ))}
          {cost.unrecorded_turns > 0 && <span className="text-xs text-muted-foreground">{cost.unrecorded_turns === 1 ? '1 earlier answer was' : `${cost.unrecorded_turns} earlier answers were`} not tracked.</span>}
        </div>
      </PopoverContent>
    </Popover>
  )
}
