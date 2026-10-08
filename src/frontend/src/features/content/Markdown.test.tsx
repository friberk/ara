import { screen, within } from '@testing-library/react'
import type { Citation } from '@/api/types'
import { renderWithProviders } from '@/test/render'
import { Markdown } from './Markdown'

const documentId = 'd1d1d1d1-0000-4000-8000-000000000001'
const cite = (chunk: string, page: number, document = documentId): Citation => ({ chunk_id: chunk, document_id: document, page, excerpt: `Excerpt from page ${page}.` })
const first = cite('aaaaaaaa-0000-4000-8000-000000000001', 3)
const second = cite('bbbbbbbb-0000-4000-8000-000000000002', 7)
const elsewhere = cite('cccccccc-0000-4000-8000-000000000003', 9, 'e2e2e2e2-0000-4000-8000-000000000002')
// jsdom models MathML as plain Elements: they have no style, so the accessibility check in role queries throws,
// and jest-dom matchers reject them. Query with hidden: true and assert on attributes and text directly.
const math = { hidden: true }
const tex = (element: Element | undefined) => element?.querySelector('annotation[encoding="application/x-tex"]')?.textContent

test('Given model Markdown, Then readable structure is rendered without executable HTML or unsafe links', () => {
  const { container } = renderWithProviders(<Markdown content={'## Results\n\n**Grounded** answer.\n\n[Unsafe](javascript:alert(1))\n\n<script>window.attack = true</script>\n\n<img src="x" onerror="window.attack = true">\n\n![Figure](https://example.org/figure.png)'} />)
  expect(screen.getByRole('heading', { name: 'Results' })).toBeVisible()
  expect(screen.getByText('Grounded')).toHaveProperty('tagName', 'STRONG')
  expect(screen.getByText('Unsafe')).not.toHaveAttribute('href')
  expect(screen.queryByRole('link')).toBeNull()
  expect(screen.queryByRole('img')).toBeNull()
  expect(container.querySelector('script, img')).toBeNull()
  expect(container).not.toHaveTextContent('window.attack')
})

test('Given an http link, Then it opens in a new tab without a referrer', () => {
  renderWithProviders(<Markdown content="Read [the paper](https://arxiv.org/abs/1706.03762)." />)
  const link = screen.getByRole('link', { name: 'the paper' })
  expect(link).toHaveAttribute('href', 'https://arxiv.org/abs/1706.03762')
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noreferrer')
})

test('Given model headings, Then they sit below the page headings', () => {
  renderWithProviders(<Markdown content={'# Overview\n\n## Method\n\n### Detail\n\n#### Aside'} />)
  expect(screen.getByRole('heading', { name: 'Overview' })).toHaveProperty('tagName', 'H3')
  expect(screen.getByRole('heading', { name: 'Method' })).toHaveProperty('tagName', 'H3')
  expect(screen.getByRole('heading', { name: 'Detail' })).toHaveProperty('tagName', 'H4')
  expect(screen.getByRole('heading', { name: 'Aside' })).toHaveProperty('tagName', 'H4')
  expect(screen.queryByRole('heading', { level: 1 })).toBeNull()
  expect(screen.queryByRole('heading', { level: 2 })).toBeNull()
})

test('Given source markers without citations, Then only valid backend markers are hidden and prose remains', () => {
  const source = '12345678-1234-1234-1234-123456789abc'
  const content = `The result is supported [source:${source}].\n\n[source:not-a-uuid] remains visible. [SOURCE:${source}] also remains visible.`
  const { container } = renderWithProviders(<Markdown content={content} />)
  expect(screen.getByText('The result is supported.')).toBeVisible()
  expect(container).not.toHaveTextContent(`[source:${source}]`)
  expect(container).toHaveTextContent('[source:not-a-uuid] remains visible.')
  expect(container).toHaveTextContent(`[SOURCE:${source}] also remains visible.`)
  expect(screen.queryByRole('button')).toBeNull()
})

test('Given \\( \\) and \\[ \\] LaTeX, Then inline and display math render in place', () => {
  const { container } = renderWithProviders(<Markdown content={'Self-attention costs \\(O(n^2 \\cdot d)\\) per layer.\n\n\\[\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V\\]'} />)
  const sentence = screen.getByText(/Self-attention costs/)
  const inline = within(sentence).getByRole('math', math)
  expect(inline.getAttribute('display')).toBeNull()
  expect(tex(inline)).toBe('O(n^2 \\cdot d)')
  const display = screen.getAllByRole('math', math).find((element) => element !== inline)
  expect(display?.getAttribute('display')).toBe('block')
  expect(tex(display)).toBe('\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V')
  expect(container).not.toHaveTextContent('(O(n^2d))')
})

test('Given display math with a % comment, Then only the comment is dropped and the next line renders', () => {
  renderWithProviders(<Markdown content={'\\[\na = 1 % first term\n+ 2\n\\]'} />)
  const display = screen.getByRole('math', math)
  expect([...display.querySelectorAll('mn')].map((number) => number.textContent)).toEqual(['1', '2'])
})

test('Given a link whose URL has escaped parentheses, Then the link keeps its URL', () => {
  renderWithProviders(<Markdown content={'Read [the note](https://example.org/f\\(x\\)).'} />)
  expect(screen.getByRole('link', { name: 'the note' })).toHaveAttribute('href', 'https://example.org/f(x)')
})

// Test-after (ARA-035 audit): trust: false shipped before a test covered it.
test('Given TeX that asks for a link, Then the math renders no link', () => {
  renderWithProviders(<Markdown content={'See \\(\\href{https://example.org}{x}\\) and \\(\\url{https://example.org}\\).'} />)
  // KaTeX would put any link in its aria-hidden HTML layer, where a pointer can still follow it.
  expect(screen.queryByRole('link', { hidden: true })).toBeNull()
})

test('Given currency amounts, Then the dollar signs stay plain text', () => {
  renderWithProviders(<Markdown content="Training cost between $5 and $10 per hour." />)
  expect(screen.getByText('Training cost between $5 and $10 per hour.')).toBeVisible()
  expect(screen.queryByRole('math', math)).toBeNull()
})

test('Given LaTeX delimiters inside code, Then the code is shown exactly as written', () => {
  renderWithProviders(<Markdown content={'Run `\\(x\\)` first.\n\n```python\nprint("\\[y\\]")\n```'} />)
  const code = screen.getAllByRole('code')
  expect(code[0]).toHaveTextContent('\\(x\\)')
  expect(code[1]).toHaveTextContent('print("\\[y\\]")')
  expect(screen.queryByRole('math', math)).toBeNull()
})

test('Given a GFM table, Then it renders as a table the reader can scroll sideways', () => {
  renderWithProviders(<Markdown content={'| Model | BLEU |\n| --- | ---: |\n| Transformer | \\(28.4\\) |'} />)
  const table = screen.getByRole('table')
  expect(within(table).getByRole('columnheader', { name: 'BLEU' })).toBeVisible()
  expect(tex(within(table).getByRole('math', math))).toBe('28.4')
})

test('Given markers for cited chunks, Then page chips appear in the sentence that cites them', () => {
  renderWithProviders(<Markdown documentId={documentId} citations={[first, second]} content={`Attention replaces recurrence [source:${first.chunk_id}].\n\nIt trains faster [source:${second.chunk_id}][source:${second.chunk_id}].`} />)
  const recurrence = screen.getByText(/Attention replaces recurrence/)
  expect(within(recurrence).getByRole('button', { name: 'Source, page 3' })).toHaveTextContent('p. 3')
  expect(within(recurrence).queryByRole('button', { name: 'Source, page 7' })).toBeNull()
  const faster = screen.getByText(/It trains faster/)
  expect(within(faster).getAllByRole('button', { name: 'Source, page 7' })).toHaveLength(1)
})

test('Given unknown or other-document markers, Then they render nothing', () => {
  const { container } = renderWithProviders(<Markdown documentId={documentId} citations={[first, elsewhere]} content={`Claim one [source:${elsewhere.chunk_id}]. Claim two [source:99999999-9999-4999-8999-999999999999].`} />)
  expect(screen.getByText('Claim one. Claim two.')).toBeVisible()
  expect(screen.queryByRole('button')).toBeNull()
  expect(container).not.toHaveTextContent('[source:')
})

test('Given an inline chip, When the reader activates it, Then onCitation receives that citation', async () => {
  const onCitation = vi.fn()
  const { user } = renderWithProviders(<Markdown documentId={documentId} citations={[first, second]} onCitation={onCitation} content={`Claim [source:${second.chunk_id}].`} />)
  await user.click(screen.getByRole('button', { name: 'Source, page 7' }))
  expect(onCitation).toHaveBeenCalledWith(second)
  expect(screen.queryByRole('dialog')).toBeNull()
})
