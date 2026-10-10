import type { Chat, ChatSummary } from '@/api/types'
import { useChats } from '@/hooks/queries/chats'
import { queryKeys } from '@/lib/query-keys'

/** The API pages chats at most 100 at a time; one paper's switcher lists that many. */
const limit = 100
export const paperChatsKey = (paperId: string) => queryKeys.chats.list({ paperId, limit })

export function asChatSummary(chat: Chat): ChatSummary {
  return { ...chat, last_activity_at: chat.created_at, message_count: 0, last_question_preview: null }
}

/** This paper's conversations, including those over several papers, latest activity first. */
export function usePaperChats(paperId: string) {
  const list = useChats({ paperId, limit })
  return { items: list.data?.items ?? [], isPending: list.isPending, isFetching: list.isFetching, error: list.error, refetch: () => void list.refetch() }
}
export type PaperChats = ReturnType<typeof usePaperChats>
