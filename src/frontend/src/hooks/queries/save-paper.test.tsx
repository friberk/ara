import { act, renderHook } from '@testing-library/react'
import { QueryClientProvider, type InfiniteData } from '@tanstack/react-query'
import { testClient } from '@/test/render'
import { mockApi } from '@/test/fetch-routes'
import type { SearchPage } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'
import { useSavePaper } from './papers'

afterEach(() => vi.unstubAllGlobals())
const hit = (provider: 'openalex' | 'semantic_scholar', external_id: string, doi: string | null) => ({ provider, external_id, title: external_id, authors: [], year: null, abstract: null, doi, external_url: null, pdf_url: null, saved_paper_id: null })

test('Given loaded search pages, When a paper is saved, Then matching hits are marked saved in place without re-fetching providers', async () => {
  const client = testClient()
  const openalex = queryKeys.search({ q: 'transformers', provider: 'openalex' })
  const scholar = queryKeys.search({ q: 'transformers', provider: 'semantic_scholar' })
  client.setQueryData<InfiniteData<SearchPage>>(openalex, { pages: [{ provider: 'openalex', items: [hit('openalex', 'W1', '10.1/ABC'), hit('openalex', 'W2', null)], next_cursor: null, total: 2 }], pageParams: [null] })
  client.setQueryData<InfiniteData<SearchPage>>(scholar, { pages: [{ provider: 'semantic_scholar', items: [hit('semantic_scholar', 'S9', '10.1/abc')], next_cursor: null, total: 1 }], pageParams: [null] })
  const saved = { id: 'p1', title: 'W1', authors: [], year: null, abstract: null, doi: '10.1/abc', sources: [hit('openalex', 'W1', '10.1/ABC')], document_status: 'metadata_only', active_document_id: null, metadata_provenance: {} }
  const { calls } = mockApi({ 'POST /papers': saved })
  const { result } = renderHook(() => useSavePaper(), { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> })
  await act(async () => { await result.current.mutateAsync({ provider: 'openalex', external_id: 'W1' }) })
  const openalexItems = client.getQueryData<InfiniteData<SearchPage>>(openalex)?.pages[0]?.items
  expect(openalexItems?.map((item) => item.saved_paper_id)).toEqual(['p1', null])
  expect(client.getQueryData<InfiniteData<SearchPage>>(scholar)?.pages[0]?.items[0]?.saved_paper_id).toBe('p1')
  expect(client.getQueryState(openalex)?.isInvalidated).toBe(false)
  expect(calls.filter((call) => call.path === '/search')).toHaveLength(0)
})
