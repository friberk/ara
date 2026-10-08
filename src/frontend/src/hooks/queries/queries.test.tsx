import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { testClient } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'
import type { Model, SearchPage } from '@/api/types'
import { useDeleteChat } from './chats'
import { useCitationSource } from './documents'
import { modelSupports, unavailableReason } from './models'
import { uniqueHits } from './search'

afterEach(() => vi.unstubAllGlobals())
function wrapper({ children }: { children: React.ReactNode }) { return <QueryClientProvider client={testClient()}>{children}</QueryClientProvider> }
const hit = (provider: 'openalex' | 'semantic_scholar', id: string) => ({ provider, external_id: id, title: id, authors: [], year: null, abstract: null, doi: null, external_url: null, pdf_url: null, saved_paper_id: null })

test('Given pages that repeat a hit across cursors, Then results are flattened without duplicates in order', () => {
  const pages = [{ provider: 'openalex', items: [hit('openalex', 'W1'), hit('openalex', 'W2')], next_cursor: 'c', total: 3 }, { provider: 'openalex', items: [hit('openalex', 'W2'), hit('openalex', 'W3')], next_cursor: null, total: 3 }] as SearchPage[]
  expect(uniqueHits(pages).map((item) => item.external_id)).toEqual(['W1', 'W2', 'W3'])
  expect(uniqueHits(undefined)).toEqual([])
})

test('Given model capabilities, Then usability and the reason shown follow the purpose', () => {
  const base = { key: 'm', provider: 'openai', model_id: 'm', display_name: 'M', status: 'configured', reasoning_efforts: ['low'], supports_streaming: true, supports_structured_output: true, context_window: 1 } as Model
  expect(modelSupports(base, 'chat')).toBe(true)
  expect(modelSupports({ ...base, status: 'unavailable' }, 'chat')).toBe(false)
  expect(unavailableReason({ ...base, status: 'unavailable' })).toBe('Not configured on the server')
  expect(unavailableReason({ ...base, supports_streaming: false }, 'chat')).toBe('Cannot stream answers')
  expect(unavailableReason({ ...base, supports_structured_output: false }, 'summary')).toBe('Cannot write summaries')
  expect(unavailableReason(base, 'chat')).toBeNull()
  expect(modelSupports(undefined, 'chat')).toBe(false)
})

test('Given a chat that is already gone, When deleted, Then it counts as deleted; other errors still surface', async () => {
  mockApi({ 'DELETE /chats/gone': () => json({ code: 'CHAT_NOT_FOUND', message: 'Chat not found.' }, 404), 'DELETE /chats/busy': () => json({ code: 'CHAT_BUSY', message: 'Wait for the current answer to finish before deleting.' }, 409) })
  const { result } = renderHook(() => useDeleteChat(), { wrapper })
  await act(async () => { await result.current.mutateAsync('gone') })
  await expect(result.current.mutateAsync('busy')).rejects.toThrow('Wait for the current answer to finish before deleting.')
})

test('Given a citation whose stored source does not match, Then the excerpt is refused', async () => {
  const citation = { chunk_id: 'k1', document_id: 'd1', page: 2, excerpt: 'cited' }
  mockApi({ 'GET /documents/d1/chunks/k1': { ...citation, page: 3, excerpt: 'other' } })
  const { result } = renderHook(() => useCitationSource(citation), { wrapper })
  await waitFor(() => expect(result.current.error?.message).toBe('This citation could not be matched to its source.'))
})
