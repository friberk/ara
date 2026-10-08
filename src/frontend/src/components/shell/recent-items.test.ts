import type { ChatSummary, SearchHistoryItem } from '@/api/types'
import { mergeRecent } from './recent-items'

const base: ChatSummary = { id: 'c1', paper_id: 'p1', document_id: 'd1', title: 'Paper discussion', title_source: 'default', created_at: '2026-10-08T10:00:00Z', paper_title: 'Attention Is All You Need', last_activity_at: '2026-10-08T12:00:00Z', message_count: 2, last_question_preview: 'Which datasets were used for machine translation?' }
const search: SearchHistoryItem = { id: 's1', provider: 'openalex', query: 'regular expressions', created_at: '2026-10-08T09:00:00Z', last_searched_at: '2026-10-08T11:00:00Z' }

test('Given a default-titled chat with questions, Then Recent names it by its latest question', () => {
  expect(mergeRecent([base], []).map((item) => item.title)).toEqual(['Which datasets were used for machine translation?'])
})

test('Given a renamed or auto-titled chat, Then Recent keeps its title', () => {
  expect(mergeRecent([{ ...base, title: 'WMT datasets', title_source: 'manual' }], [])[0]?.title).toBe('WMT datasets')
})

test('Given an empty chat, Then Recent leaves it out while searches and active chats interleave by time', () => {
  const empty = { ...base, id: 'c2', message_count: 0, last_question_preview: null, last_activity_at: '2026-10-08T13:00:00Z' }
  expect(mergeRecent([empty, base], [search]).map((item) => `${item.kind}:${item.id}`)).toEqual(['chat:c1', 'search:s1'])
})
