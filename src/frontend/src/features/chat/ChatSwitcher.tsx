import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Pencil, SquarePen, Trash2 } from 'lucide-react'
import type { ChatSummary, Paper } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DeleteChatDialog, RenameChatDialog } from '@/components/shell/chat-dialogs'
import { chatDisplayTitle } from '@/components/shell/recent-items'
import { ChatHistory } from './ChatHistory'
import { usesEarlierPdf } from './chat-pdf'
import type { PaperChats } from './use-paper-chats'

/** The pane's top row: the open conversation's title and actions, this paper's chat history, and a new conversation. */
export function ChatSwitcher({ paper, chats, chat, chatId }: { paper: Paper; chats: PaperChats; chat: ChatSummary | undefined; chatId: string | undefined }) {
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<'rename' | 'delete' | null>(null)
  const startNew = () => navigate(`/papers/${paper.id}`)
  const title = chat ? chatDisplayTitle(chat) : chatId ? 'Conversation' : 'New conversation'
  const earlier = !!chat && usesEarlierPdf(paper, chat)
  return (
    <div className="flex h-12 shrink-0 items-center gap-1 px-2">
      {chat ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="ghost" size="sm" aria-label={earlier ? `${title}, earlier PDF` : undefined} className="h-8 min-w-0 max-w-full gap-1.5 px-2.5 text-sm font-medium">
              <span className="truncate">{title}</span>
              {earlier && <Badge variant="outline" className="font-normal text-muted-foreground">Earlier PDF</Badge>}
              <ChevronDown aria-hidden="true" className="text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => setDialog('rename')}><Pencil aria-hidden="true" />Rename</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}><Trash2 aria-hidden="true" />Delete</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <span className="truncate px-2.5 text-sm font-medium">{title}</span>
      )}
      <div className="ml-auto flex items-center gap-1">
        <ChatHistory paper={paper} chats={chats} chatId={chatId} />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button type="button" variant="ghost" size="icon-sm" aria-label="New conversation" onClick={startNew} className="text-muted-foreground hover:text-foreground"><SquarePen aria-hidden="true" /></Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">New conversation</TooltipContent>
        </Tooltip>
      </div>
      {chat && dialog === 'rename' && <RenameChatDialog chat={chat} onClose={() => setDialog(null)} />}
      {chat && dialog === 'delete' && <DeleteChatDialog chat={chat} onClose={() => setDialog(null)} />}
    </div>
  )
}
