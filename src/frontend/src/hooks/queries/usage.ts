import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, query } from '@/api/client'
import type { ChatUsage, GenerationSettings } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

/**
 * Context used by a chat's latest answer against the selected model's budget, and the chat's cost so far.
 * The selection is part of the key, so switching models asks again; the previous numbers stay up meanwhile.
 * A server without the endpoint, or an odd reply, gives no data and the meter stays hidden.
 */
export function useChatUsage(chatId: string, { model, reasoning_effort }: GenerationSettings) {
  return useQuery({
    queryKey: queryKeys.usage.selection(chatId, model, reasoning_effort),
    queryFn: async ({ signal }) => {
      const usage = await api<ChatUsage>(`/chats/${encodeURIComponent(chatId)}/usage${query({ model, reasoning_effort })}`, { signal })
      if (!usage?.context || !usage.cost) throw new Error('The usage reply was incomplete.')
      return usage
    },
    // Until the selection is known (settings still loading) there is nothing valid to ask for.
    enabled: !!model && !!reasoning_effort,
    placeholderData: keepPreviousData,
    retry: false,
  })
}
