import type { ChatSummary, SearchHistoryItem } from '@/api/types'
import { providerLabels } from '@/api/types'

export type RecentItem =
  | { kind: 'chat'; id: string; title: string; detail: string | null; href: string; at: string; chat: ChatSummary }
  | { kind: 'search'; id: string; title: string; detail: string; href: string; at: string; search: SearchHistoryItem }

export function searchHref(item: Pick<SearchHistoryItem, 'query' | 'provider'>) {
  return `/search?${new URLSearchParams({ q: item.query, provider: item.provider })}`
}
export function chatHref(chat: Pick<ChatSummary, 'id' | 'paper_id'>) { return `/papers/${chat.paper_id}/chats/${chat.id}` }

/** Chats and searches interleaved by their latest activity, newest first. */
export function mergeRecent(chats: ChatSummary[], searches: SearchHistoryItem[], limit = 15): RecentItem[] {
  const items: RecentItem[] = [
    ...chats.map((chat) => ({ kind: 'chat' as const, id: chat.id, title: chat.title || 'Untitled conversation', detail: chat.paper_title, href: chatHref(chat), at: chat.last_activity_at, chat })),
    ...searches.map((search) => ({ kind: 'search' as const, id: search.id, title: search.query, detail: providerLabels[search.provider], href: searchHref(search), at: search.last_searched_at, search })),
  ]
  // Defensive at the data boundary: a row without a timestamp sorts last instead of breaking the sidebar.
  return items.sort((a, b) => String(b.at ?? '').localeCompare(String(a.at ?? ''))).slice(0, limit)
}
