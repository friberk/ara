import type { Provider } from '@/api/types'

// Hierarchical keys: invalidating a prefix such as queryKeys.papers.all refreshes every list and detail below it.
export const queryKeys = {
  search: (params: { q: string; provider: Provider }) => ['search', params] as const,
  searchHistory: { all: ['search-history'] as const, list: (limit: number) => ['search-history', 'list', limit] as const },
  papers: {
    all: ['papers'] as const,
    list: (filter: string) => ['papers', 'list', filter] as const,
    detail: (id: string) => ['papers', 'detail', id] as const,
  },
  chats: {
    all: ['chats'] as const,
    list: (filters: { paperId?: string | null; limit?: number }) => ['chats', 'list', filters] as const,
  },
  messages: (chatId: string) => ['messages', chatId] as const,
  summaries: (paperId: string) => ['summaries', paperId] as const,
  fulltext: (paperId: string) => ['fulltext', paperId] as const,
  jobs: {
    all: ['jobs'] as const,
    list: (filters: { paperId?: string | null; kind?: string | null; active?: boolean | null }) => ['jobs', 'list', filters] as const,
    detail: (id: string) => ['jobs', 'detail', id] as const,
  },
  citation: (documentId: string, chunkId: string) => ['citation', documentId, chunkId] as const,
  models: ['models'] as const,
  settings: ['settings'] as const,
}
