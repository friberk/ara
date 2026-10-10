import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Pencil, SquarePen, Trash2 } from 'lucide-react'
import type { ChatSummary, Paper } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DeleteChatDialog, RenameChatDialog } from '@/components/shell/chat-dialogs'
import { chatDisplayTitle, chatHref } from '@/components/shell/recent-items'
import type { PaperChats } from './use-paper-chats'

const sameDay = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const sameYear = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
const otherYear = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
function formatActivity(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return sameDay.format(date)
  return (date.getFullYear() === now.getFullYear() ? sameYear : otherYear).format(date)
}

const pdfNotes = { earlier: { badge: 'Earlier PDF', spoken: 'earlier PDF' }, removed: { badge: 'PDF removed', spoken: 'PDF removed' } }

// Questions compare without case or trailing punctuation: auto-titles drop the question mark and may end in "…".
const comparable = (text: string) => text.replace(/[\s.,;:!?…\-–—]+$/u, '').toLowerCase()
/** The second line of a row: the latest question when it is not already the name, or why there is none. */
function secondLine(chat: ChatSummary) {
  if (chat.last_question_preview) return comparable(chat.last_question_preview).startsWith(comparable(chatDisplayTitle(chat))) ? null : chat.last_question_preview
  return chat.message_count === 0 ? 'No questions yet' : null
}

/** The pane's top row: switch between this paper's conversations, rename or delete the open one, or start anew. */
export function ChatSwitcher({ paper, chats, chat, chatId }: { paper: Paper; chats: PaperChats; chat: ChatSummary | undefined; chatId: string | undefined }) {
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<'rename' | 'delete' | null>(null)
  const startNew = () => navigate(`/papers/${paper.id}`)
  const title = chat ? chatDisplayTitle(chat) : chatId ? 'Conversation' : 'New conversation'
  // The PDF this chat pinned for this paper, which a newer upload does not replace, or which was removed (ARA-097).
  const pinned = (item: ChatSummary) => item.papers.find((included) => included.paper_id === paper.id)
  const pdfNote = (item: ChatSummary) => {
    const link = pinned(item)
    return link?.pdf_removed ? pdfNotes.removed : link && link.document_id !== paper.active_document_id ? pdfNotes.earlier : null
  }
  const note = chat ? pdfNote(chat) : null
  return (
    <div className="flex h-12 shrink-0 items-center gap-1 px-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="sm" aria-label={note ? `${title}, ${note.spoken}` : undefined} className="h-8 min-w-0 max-w-full gap-1.5 px-2.5 text-sm font-medium">
            <span className="truncate">{title}</span>
            {note && <Badge variant="outline" className="font-normal text-muted-foreground">{note.badge}</Badge>}
            <ChevronDown aria-hidden="true" className="text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[min(22rem,calc(100vw-2rem))]">
          <DropdownMenuLabel>Conversations about this paper</DropdownMenuLabel>
          {chats.isPending && <DropdownMenuItem disabled>Loading conversations…</DropdownMenuItem>}
          {!!chats.error && !chats.items.length && <DropdownMenuItem onSelect={chats.refetch}>Conversations could not load. Try again</DropdownMenuItem>}
          {!chats.isPending && !chats.error && !chats.items.length && <DropdownMenuItem disabled>No conversations yet</DropdownMenuItem>}
          <DropdownMenuRadioGroup value={chatId ?? ''} onValueChange={(id) => { const item = chats.items.find((entry) => entry.id === id); navigate(item ? chatHref(item) : `/papers/${paper.id}/chats/${id}`) }}>
            {chats.items.map((item) => (
              <DropdownMenuRadioItem key={item.id} value={item.id} className="items-start py-1.5">
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate">{chatDisplayTitle(item)}</span>
                    <time dateTime={item.last_activity_at} className="ml-auto shrink-0 text-xs text-muted-foreground tabular">{formatActivity(item.last_activity_at)}</time>
                  </span>
                  {secondLine(item) && <span className="truncate text-xs text-muted-foreground">{secondLine(item)}</span>}
                  {pdfNote(item) && <Badge variant="outline" className="mt-0.5 font-normal text-muted-foreground">{pdfNote(item)?.badge}</Badge>}
                </div>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={startNew}><SquarePen aria-hidden="true" />New conversation</DropdownMenuItem>
          {chat && (
            <>
              <DropdownMenuItem onSelect={() => setDialog('rename')}><Pencil aria-hidden="true" />Rename</DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}><Trash2 aria-hidden="true" />Delete</DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button type="button" variant="ghost" size="icon-sm" aria-label="New conversation" onClick={startNew} className="ml-auto text-muted-foreground hover:text-foreground"><SquarePen aria-hidden="true" /></Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">New conversation</TooltipContent>
      </Tooltip>
      {chat && dialog === 'rename' && <RenameChatDialog chat={chat} onClose={() => setDialog(null)} />}
      {chat && dialog === 'delete' && <DeleteChatDialog chat={chat} onClose={() => setDialog(null)} />}
    </div>
  )
}
