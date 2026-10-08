import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Pencil, SquarePen, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import type { ChatSummary, Paper } from '@/api/types'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { chatDisplayTitle } from '@/components/shell/recent-items'
import { useDeleteChat, useRenameChat } from '@/hooks/queries/chats'
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

// Questions compare without case or trailing punctuation: auto-titles drop the question mark and may end in "…".
const comparable = (text: string) => text.replace(/[\s.,;:!?…\-–—]+$/u, '').toLowerCase()
/** The second line of a row: the latest question when it is not already the name, or why there is none. */
function secondLine(chat: ChatSummary) {
  if (chat.last_question_preview) return comparable(chat.last_question_preview).startsWith(comparable(chatDisplayTitle(chat))) ? null : chat.last_question_preview
  return chat.message_count === 0 ? 'No questions yet' : null
}

function RenameDialog({ chat, onClose }: { chat: ChatSummary; onClose: () => void }) {
  const [title, setTitle] = useState(chat.title)
  const rename = useRenameChat()
  const trimmed = title.trim()
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (trimmed) rename.mutate({ chatId: chat.id, title: trimmed }, { onSuccess: () => { toast.success('Conversation renamed'); onClose() } }) }}>
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
            <DialogDescription>{chat.paper_title ?? 'Paper conversation'}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="rename-current-chat">Conversation name</Label>
            <Input id="rename-current-chat" value={title} maxLength={200} autoFocus onChange={(event) => setTitle(event.target.value)} />
          </div>
          <ErrorNotice error={rename.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!trimmed || trimmed === chat.title || rename.isPending}>{rename.isPending ? 'Saving…' : 'Save name'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteDialog({ chat, onClose, onDeleted }: { chat: ChatSummary; onClose: () => void; onDeleted: () => void }) {
  const remove = useDeleteChat()
  return (
    <AlertDialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
          <AlertDialogDescription>“{chat.title}” and its answers will be removed. The paper and its summaries stay in your library.</AlertDialogDescription>
        </AlertDialogHeader>
        <ErrorNotice error={remove.error} />
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={remove.isPending} onClick={(event) => { event.preventDefault(); remove.mutate(chat.id, { onSuccess: () => { toast.success('Conversation deleted'); onDeleted() } }) }}>
            {remove.isPending ? 'Deleting…' : 'Delete conversation'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** The pane's top row: switch between this paper's conversations, rename or delete the open one, or start anew. */
export function ChatSwitcher({ paper, chats, chat, chatId }: { paper: Paper; chats: PaperChats; chat: ChatSummary | undefined; chatId: string | undefined }) {
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<'rename' | 'delete' | null>(null)
  const startNew = () => navigate(`/papers/${paper.id}`)
  const title = chat ? chatDisplayTitle(chat) : chatId ? 'Conversation' : 'New conversation'
  const earlier = (item: ChatSummary) => item.document_id !== paper.active_document_id
  return (
    <div className="flex h-12 shrink-0 items-center gap-1 px-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="h-8 min-w-0 max-w-full gap-1.5 px-2.5 text-sm font-medium">
            <span className="truncate">{title}</span>
            {chat && earlier(chat) && <Badge variant="outline" className="font-normal text-muted-foreground">Earlier PDF</Badge>}
            <ChevronDown aria-hidden="true" className="text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[min(22rem,calc(100vw-2rem))]">
          <DropdownMenuLabel>Conversations about this paper</DropdownMenuLabel>
          {chats.isPending && <DropdownMenuItem disabled>Loading conversations…</DropdownMenuItem>}
          {!!chats.error && !chats.items.length && <DropdownMenuItem onSelect={chats.refetch}>Conversations could not load. Try again</DropdownMenuItem>}
          {!chats.isPending && !chats.error && !chats.items.length && <DropdownMenuItem disabled>No conversations yet</DropdownMenuItem>}
          <DropdownMenuRadioGroup value={chatId ?? ''} onValueChange={(id) => navigate(`/papers/${paper.id}/chats/${id}`)}>
            {chats.items.map((item) => (
              <DropdownMenuRadioItem key={item.id} value={item.id} className="items-start py-1.5">
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate">{chatDisplayTitle(item)}</span>
                    <time dateTime={item.last_activity_at} className="ml-auto shrink-0 text-xs text-muted-foreground tabular">{formatActivity(item.last_activity_at)}</time>
                  </span>
                  {secondLine(item) && <span className="truncate text-xs text-muted-foreground">{secondLine(item)}</span>}
                  {earlier(item) && <Badge variant="outline" className="mt-0.5 font-normal text-muted-foreground">Earlier PDF</Badge>}
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
      {chat && dialog === 'rename' && <RenameDialog chat={chat} onClose={() => setDialog(null)} />}
      {chat && dialog === 'delete' && <DeleteDialog chat={chat} onClose={() => setDialog(null)} onDeleted={() => { setDialog(null); navigate(`/papers/${paper.id}`, { replace: true }) }} />}
    </div>
  )
}
