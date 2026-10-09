import { screen } from '@testing-library/react'
import type { SearchHit } from '@/api/types'
import { mockApi } from '@/test/fetch-routes'
import { renderWithProviders } from '@/test/render'
import { PaperCard } from './PaperCard'

const hit: SearchHit = { provider: 'semantic_scholar', external_id: 's2', title: 'Research', authors: [], year: null, doi: null, abstract: null, external_url: null, pdf_url: 'https://arxiv.org/pdf/paper', is_open_access: true }
afterEach(() => vi.unstubAllGlobals())
test('Given a provider-reported open copy, Then the result labels the report without requesting its PDF', () => {
  const { calls } = mockApi({})
  renderWithProviders(<PaperCard hit={hit} />)
  expect(screen.getByText('Open copy reported')).toBeVisible()
  expect(calls).toHaveLength(0)
})
test('Given unknown access, Then no open-access report is invented', () => {
  mockApi({})
  renderWithProviders(<PaperCard hit={{ ...hit, is_open_access: null }} />)
  expect(screen.queryByText('Open copy reported')).not.toBeInTheDocument()
})
