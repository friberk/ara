import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { History } from 'lucide-react'
import type { ChatSummary, Paper } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { chatDisplayTitle, chatHref } from '@/components/shell/recent-items'
import { compactRelativeTime, fullDateTime, longRelativeTime, useNow } from '@/lib/relative-time'
import { usesEarlierPdf } from './chat-pdf'
import type { PaperChats } from './use-paper-chats'

/** A filter earns its row once the list outgrows a glance. */
const filterThreshold = 7

// Questions compare without case or trailing punctuation: auto-titles drop the question mark and may end in "…".
const comparable = (text: string) => text.replace(/[\s.,;:!?…\-–—]+$/u, '').toLowerCase()
/** The second line of a row: the latest question when it is not already the name, or why there is none. */
function secondLine(chat: ChatSummary) {
  if (chat.last_question_preview) return comparable(chat.last_question_preview).startsWith(comparable(chatDisplayTitle(chat))) ? null : chat.last_question_preview
  return chat.message_count === 0 ? 'No questions yet' : null
}

/** Compact relative time for the eye, the long form for screen readers, the exact moment on hover. */
function ActivityTime({ iso, now }: { iso: string; now: number }) {
  const compact = compactRelativeTime(iso, now)
  if (!compact) return null
  return (
    <time dateTime={iso} title={fullDateTime(iso) ?? undefined} className="ml-auto shrink-0 pl-2 text-xs text-muted-foreground tabular">
      <span aria-hidden="true">{compact}</span>
      <span className="sr-only">{longRelativeTime(iso, now)}</span>
    </time>
  )
}

function Rows({ paper, chats, chatId, close }: { paper: Paper; chats: PaperChats; chatId: string | undefined; close: () => void }) {
  const navigate = useNavigate()
  const now = useNow()
  if (chats.isPending) return <p role="status" className="px-2 py-6 text-center text-sm text-muted-foreground">Loading chats…</p>
  if (chats.error && !chats.items.length) {
    return (
      <div role="alert" className="grid justify-items-center gap-2 px-2 py-5 text-center text-sm text-muted-foreground">
        Chats could not load.
        <Button type="button" variant="outline" size="sm" onClick={chats.refetch}>Try again</Button>
      </div>
    )
  }
  if (!chats.items.length) return <p className="px-2 py-6 text-center text-sm text-muted-foreground">No chats yet</p>
  const rowValue = (item: ChatSummary) => `${chatDisplayTitle(item)} ${item.last_question_preview ?? ''} ${item.id}`
  const active = chats.items.find((item) => item.id === chatId)
  return (
    <Command defaultValue={active ? rowValue(active) : undefined} loop className="p-0" tabIndex={-1} data-testid="chat-history-command">
      {chats.items.length > filterThreshold && <CommandInput placeholder="Filter chats" aria-label="Filter chats" />}
      <CommandList className="max-h-[min(20rem,60vh)] p-1">
        <CommandEmpty>No matching chats</CommandEmpty>
        {chats.items.map((item) => {
          const second = secondLine(item)
          return (
            <CommandItem
              key={item.id}
              value={rowValue(item)}
              data-checked={item.id === chatId}
              aria-current={item.id === chatId ? 'true' : undefined}
              onSelect={() => { close(); navigate(chatHref(item)) }}
              className="items-start py-1.5"
            >
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="flex min-w-0 items-baseline">
                  <span className="truncate">{chatDisplayTitle(item)}</span>
                  {usesEarlierPdf(paper, item) && <Badge variant="outline" className="ml-2 shrink-0 font-normal text-muted-foreground">Earlier PDF</Badge>}
                  <ActivityTime iso={item.last_activity_at} now={now} />
                </span>
                {second && <span className="truncate text-xs text-muted-foreground">{second}</span>}
              </div>
            </CommandItem>
          )
        })}
      </CommandList>
    </Command>
  )
}

/** The History icon: opens this paper's conversations, newest first. The icon and the paper's own pane say what it is. */
export function ChatHistory({ paper, chats, chatId }: { paper: Paper; chats: PaperChats; chatId: string | undefined }) {
  const [open, setOpen] = useState(false)
  const content = useRef<HTMLDivElement>(null)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button type="button" variant="ghost" size="icon-sm" aria-label="Chat history" className="text-muted-foreground hover:text-foreground"><History aria-hidden="true" /></Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">Chat history</TooltipContent>
      </Tooltip>
      <PopoverContent
        ref={content}
        align="end"
        collisionPadding={16}
        aria-label="Chat history for this paper"
        className="w-[min(22rem,calc(100vw-2rem))] gap-0 p-0"
        // Without a filter field nothing inside takes focus, so the list itself does and arrow keys work at once.
        onOpenAutoFocus={(event) => {
          const command = content.current?.querySelector<HTMLElement>('[cmdk-root]')
          if (command && !command.querySelector('input')) { event.preventDefault(); command.focus() }
        }}
      >
        <Rows paper={paper} chats={chats} chatId={chatId} close={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}
