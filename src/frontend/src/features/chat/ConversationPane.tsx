import { useNavigate } from 'react-router-dom'
import { MessageSquareDashed } from 'lucide-react'
import type { Paper } from '@/api/types'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ChatSwitcher } from './ChatSwitcher'
import { ConversationThread } from './ConversationThread'
import { NewConversation } from './NewConversation'
import { usePaperChats } from './use-paper-chats'

export type ConversationPaneProps = {
  paper: Paper
  /** The chat in the URL (/papers/:paperId/chats/:chatId); undefined shows a new-conversation start. */
  chatId?: string
}

/**
 * The conversation side of the paper workspace. Fills its parent's height, scrolls its own thread and docks
 * the composer at the bottom. Citation chips call useOptionalWorkspace()?.showSource when inside the workspace.
 */
export function ConversationPane({ paper, chatId }: ConversationPaneProps) {
  const navigate = useNavigate()
  const chats = usePaperChats(paper.id)
  const chat = chatId ? chats.items.find((item) => item.id === chatId) : undefined
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <ChatSwitcher paper={paper} chats={chats} chat={chat} chatId={chatId} />
      {!chatId ? (
        <NewConversation paper={paper} />
      ) : chat ? (
        <ConversationThread key={chat.id} paper={paper} chat={chat} />
      ) : chats.isPending || chats.isFetching ? (
        // A chat created elsewhere (the home composer) may be missing from a cached list until it refetches.
        <div role="status" aria-label="Loading conversation" className="mx-auto grid w-full max-w-3xl gap-3 px-4 pt-2">
          <Skeleton className="h-28 w-full rounded-2xl" /><Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
        </div>
      ) : chats.error ? (
        <div className="mx-auto w-full max-w-3xl px-4 pt-2"><ErrorNotice error={chats.error} retry={chats.refetch} /></div>
      ) : (
        <EmptyState icon={MessageSquareDashed} title="Conversation not found" className="flex-1" action={<Button type="button" onClick={() => navigate(`/papers/${paper.id}`)}>New conversation</Button>}>
          It may have been deleted. Ask a new question about this paper instead.
        </EmptyState>
      )}
    </div>
  )
}
