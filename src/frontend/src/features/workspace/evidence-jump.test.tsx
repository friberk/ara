// The evidence jump from a Sources chip, across the content module and the reader's sentence selection.
import { screen } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { SourceList } from '@/features/content'
import { renderWithProviders } from '@/test/render'
import { selectEvidence } from './evidence'
import { headsClaim, interpretability, page7 } from './evidence.fixtures'

const onPage1: Citation = { chunk_id: '11111111-1111-4111-8111-111111111111', document_id: 'd1', page: 1, excerpt: 'The Transformer relies entirely on attention.' }
const onPage7: Citation = { chunk_id: '77777777-7777-4777-8777-777777777777', document_id: 'd1', page: 7, excerpt: page7 }
// An answer whose first paragraph shares many words (convolution, self-attention, position-wise feed-forward
// layers) with an unrelated sentence of the page-7 chunk.
const answer = [
  `The Transformer replaces recurrence and convolution with self-attention layers and position-wise feed-forward layers, the approach the model takes throughout. [source:${onPage1.chunk_id}]`,
  '',
  `${headsClaim} [source:${onPage7.chunk_id}]`,
].join('\n')

test('Given the Sources chip for page 7, When the reader selects its evidence, Then the unrelated convolution sentence is not chosen', async () => {
  const onSelect = vi.fn()
  const { user } = renderWithProviders(<SourceList documents={new Set(['d1'])} citations={[onPage1, onPage7]} context={answer} onSelect={onSelect} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  const [citation, claim] = onSelect.mock.lastCall as [Citation, string]
  expect(citation).toBe(onPage7)
  const chosen = selectEvidence(citation.excerpt, claim).map((sentence) => sentence.replace(/\s+/g, ' '))
  expect(chosen.join(' ')).not.toMatch(/Even with k = n/)
  expect(chosen).toContain(interpretability[2])
})
