import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, apiVoid, json, query, remove } from '@/api/client'
import type { Chat, ChatSummary, Collection, Message } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

/** Recent conversations across papers, or for one paper, ordered by latest activity. */
export function useChats(filters: { paperId?: string | null; limit?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.chats.list(filters),
    queryFn: ({ signal }) => api<Collection<ChatSummary>>(`/chats${query({ paper_id: filters.paperId, limit: filters.limit ?? 30 })}`, { signal }),
    retry: false,
  })
}

/** One chat with its papers, for a link from a paper the chat may no longer cover. */
export function useChat(chatId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.chats.detail(chatId ?? ''),
    queryFn: ({ signal }) => api<ChatSummary>(`/chats/${chatId}`, { signal }),
    enabled: !!chatId,
    retry: false,
  })
}

/** A chat over one or more ready library papers; the first one's page is the chat's URL. */
export function useCreateChat() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ paperIds, title }: { paperIds: string[]; title?: string }) => api<Chat>('/chats', json('POST', { paper_ids: paperIds, ...(title ? { title } : {}) })),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.chats.all }),
  })
}

/**
 * Removes a paper; the response names the chat's new first paper. Papers join a chat with the question whose pills
 * mention them (ARA-096); the only paper the client adds on its own is one just removed, which Undo puts back (ARA-110).
 */
export function useChatPapers(chatId: string) {
  const client = useQueryClient()
  const settled = () => void client.invalidateQueries({ queryKey: queryKeys.chats.all })
  const remove = useMutation({ mutationFn: (paperId: string) => api<Chat>(`/chats/${chatId}/papers/${paperId}`, { method: 'DELETE' }), onSuccess: settled })
  const restore = useMutation({ mutationFn: (paperId: string) => api<Chat>(`/chats/${chatId}/papers`, json('POST', { paper_id: paperId })), onSuccess: settled })
  return { remove, restore }
}

export function useRenameChat() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ chatId, title }: { chatId: string; title: string }) => api<Chat>(`/chats/${chatId}`, json('PATCH', { title })),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.chats.all }),
  })
}

export function useDeleteChat() {
  const client = useQueryClient()
  return useMutation({
    // A chat that is already gone counts as deleted.
    mutationFn: async (chatId: string) => { try { await apiVoid(`/chats/${chatId}`, remove) } catch (error) { if (!(error instanceof ApiError && error.status === 404)) throw error } },
    onSuccess: (_result, chatId) => { client.removeQueries({ queryKey: queryKeys.messages(chatId) }); void client.invalidateQueries({ queryKey: queryKeys.chats.all }) },
  })
}

/** Saved messages; polls while a saved answer is still processing and no local stream owns it. */
export function useMessages(chatId: string | undefined, options: { streaming?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.messages(chatId ?? ''),
    queryFn: ({ signal }) => api<Collection<Message>>(`/chats/${chatId}/messages`, { signal }),
    enabled: !!chatId,
    refetchInterval: (current) => !options.streaming && current.state.data?.items.some((message) => message.state === 'processing') ? 1500 : false,
  })
}
