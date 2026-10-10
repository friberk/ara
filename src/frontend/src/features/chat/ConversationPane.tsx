import { Navigate, useNavigate } from 'react-router-dom'
import { MessageSquareDashed } from 'lucide-react'
import type { Paper } from '@/api/types'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { chatHref } from '@/components/shell/recent-items'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useChat } from '@/hooks/queries/chats'
import { ChatPapers } from './ChatPapers'
import { ChatSwitcher } from './ChatSwitcher'
import { ConversationThread } from './ConversationThread'
import { NewConversation } from './NewConversation'
import { useChatPaperEditing } from './use-chat-paper-editing'
import { usePaperChats } from './use-paper-chats'

export type ConversationPaneProps = {
  paper: Paper
  /** The chat in the URL (/papers/:paperId/chats/:chatId); undefined shows a new-conversation start. */
  chatId?: string
}

/**
 * The conversation side of the paper workspace. Fills its parent's height, scrolls its own thread and docks
 * the composer at the bottom. Citation chips call useOptionalWorkspace()?.showSource when inside the workspace.
 * A chat lives at its first paper's address (ARA-088): opened from another of its papers, or from a link to a paper it
 * no longer covers, it moves there.
 */
export function ConversationPane({ paper, chatId }: ConversationPaneProps) {
  const navigate = useNavigate()
  const chats = usePaperChats(paper.id)
  const listed = chatId ? chats.items.find((item) => item.id === chatId) : undefined
  const lookup = useChat(chatId && !listed && !chats.isPending && !chats.isFetching ? chatId : undefined)
  const chat = listed ?? (lookup.data?.id === chatId ? lookup.data : undefined)
  const editing = useChatPaperEditing(chat, paper)
  if (chat && chat.paper_id !== paper.id) return <Navigate to={chatHref(chat)} replace />
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <ChatSwitcher paper={paper} chats={chats} chat={chat} chatId={chatId} />
      {chat && <ChatPapers papers={chat.papers} onRemove={editing.remove} removing={editing.removing} />}
      {!chatId ? (
        <NewConversation paper={paper} />
      ) : chat ? (
        <ConversationThread key={chat.id} paper={paper} chat={chat} papers={{ selected: editing.selected, onSelect: editing.toggle }} />
      ) : chats.isPending || chats.isFetching || lookup.isFetching ? (
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
