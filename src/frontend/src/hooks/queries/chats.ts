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

export function useCreateChat(paperId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => api<Chat>(`/papers/${paperId}/chats`, json('POST', title ? { title } : {})),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.chats.all }),
  })
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
