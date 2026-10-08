import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '@/api/client'
import type { Chat, ChatSummary, Collection } from '@/api/types'
import { useChats } from '@/hooks/queries/chats'
import { queryKeys } from '@/lib/query-keys'

/** The API pages chats at most 100 at a time; one paper's switcher lists that many. */
const limit = 100
export const paperChatsKey = (paperId: string) => queryKeys.chats.list({ paperId, limit })

export function asChatSummary(chat: Chat, paperTitle: string | null = null): ChatSummary {
  return { ...chat, paper_title: paperTitle, last_activity_at: chat.created_at, message_count: 0, last_question_preview: null }
}

/**
 * This paper's conversations, latest activity first. A server without the workspace-history API (ARA-034)
 * answers GET /chats with 404; then the older per-paper list is used, without previews.
 */
export function usePaperChats(paperId: string) {
  const list = useChats({ paperId, limit })
  const missing = list.error instanceof ApiError && list.error.status === 404
  const legacy = useQuery({
    queryKey: [...queryKeys.chats.all, 'paper', paperId],
    queryFn: ({ signal }) => api<Collection<Chat>>(`/papers/${paperId}/chats`, { signal }),
    enabled: missing,
  })
  if (missing) return { items: (legacy.data?.items ?? []).map((chat) => asChatSummary(chat)), isPending: legacy.isPending, isFetching: legacy.isFetching, error: legacy.error, refetch: () => void legacy.refetch() }
  return { items: list.data?.items ?? [], isPending: list.isPending, isFetching: list.isFetching, error: list.error, refetch: () => void list.refetch() }
}
export type PaperChats = ReturnType<typeof usePaperChats>
