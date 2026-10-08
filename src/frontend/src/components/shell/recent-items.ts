import type { ChatSummary, SearchHistoryItem } from '@/api/types'
import { providerLabels } from '@/api/types'

export type RecentItem =
  | { kind: 'chat'; id: string; title: string; detail: string | null; href: string; at: string; chat: ChatSummary }
  | { kind: 'search'; id: string; title: string; detail: string; href: string; at: string; search: SearchHistoryItem }

export function searchHref(item: Pick<SearchHistoryItem, 'query' | 'provider'>) {
  return `/search?${new URLSearchParams({ q: item.query, provider: item.provider })}`
}
export function chatHref(chat: Pick<ChatSummary, 'id' | 'paper_id'>) { return `/papers/${chat.paper_id}/chats/${chat.id}` }

/** A chat still on its default title (created before auto-titling) is named by its latest question. */
export function chatDisplayTitle(chat: Pick<ChatSummary, 'title' | 'title_source' | 'last_question_preview'>) {
  if (chat.title_source === 'default' && chat.last_question_preview) return chat.last_question_preview
  return chat.title || 'Untitled conversation'
}

/** Chats with messages and searches, interleaved by their latest activity, newest first. */
export function mergeRecent(chats: ChatSummary[], searches: SearchHistoryItem[], limit = 15): RecentItem[] {
  const items: RecentItem[] = [
    ...chats.filter((chat) => chat.message_count > 0).map((chat) => ({ kind: 'chat' as const, id: chat.id, title: chatDisplayTitle(chat), detail: chat.paper_title, href: chatHref(chat), at: chat.last_activity_at, chat })),
    ...searches.map((search) => ({ kind: 'search' as const, id: search.id, title: search.query, detail: providerLabels[search.provider], href: searchHref(search), at: search.last_searched_at, search })),
  ]
  // Defensive at the data boundary: a row without a timestamp sorts last instead of breaking the sidebar.
  return items.sort((a, b) => String(b.at ?? '').localeCompare(String(a.at ?? ''))).slice(0, limit)
}
