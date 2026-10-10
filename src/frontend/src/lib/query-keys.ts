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
  // Outside the papers prefix, so refreshing papers never re-reads a preview of deleted ones.
  deletionPreview: (ids: readonly string[]) => ['deletion-preview', ...ids] as const,
  chats: {
    all: ['chats'] as const,
    list: (filters: { paperId?: string | null; limit?: number }) => ['chats', 'list', filters] as const,
    detail: (id: string) => ['chats', 'detail', id] as const,
  },
  messages: (chatId: string) => ['messages', chatId] as const,
  // The prefix refreshes every model the meter has shown for the chat; the full key adds the selection.
  usage: { chat: (chatId: string) => ['usage', chatId] as const, selection: (chatId: string, model: string, effort: string) => ['usage', chatId, model, effort] as const },
  summaries: (paperId: string) => ['summaries', paperId] as const,
  fulltext: (paperId: string) => ['fulltext', paperId] as const,
  jobs: {
    all: ['jobs'] as const,
    list: (filters: { paperId?: string | null; kind?: string | null; active?: boolean | null }) => ['jobs', 'list', filters] as const,
    detail: (id: string) => ['jobs', 'detail', id] as const,
  },
  citation: (documentId: string, chunkId: string) => ['citation', documentId, chunkId] as const,
  documents: { all: ['documents'] as const, detail: (id: string) => ['documents', id] as const },
  // Like the deletion preview, outside the papers prefix and read afresh each time (ARA-097).
  pdfRemovalPreview: (paperId: string) => ['pdf-removal-preview', paperId] as const,
  features: ['features'] as const,
  models: ['models'] as const,
  settings: ['settings'] as const,
  retrieval: {
    profiles: ['retrieval', 'profiles'] as const,
    settings: ['retrieval', 'settings'] as const,
    estimate: (profile: string) => ['retrieval', 'estimate', profile] as const,
    paper: (paperId: string) => ['retrieval', 'paper', paperId] as const,
    memory: (chatId: string) => ['retrieval', 'memory', chatId] as const,
  },
}
