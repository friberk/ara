import { markdownToText } from './markdown-text'

describe('markdownToText', () => {
  test('Given layout Markdown headings and emphasis, Then the words remain and blocks stay apart', () => {
    expect(markdownToText('# **Sparse Retrieval**\n\n## Abstract\n\nWe study _sparse_ retrieval.')).toBe(
      'Sparse Retrieval\n\nAbstract\n\nWe study sparse retrieval.',
    )
  })

  test('Given a GFM table, Then each row is a line of its cells and the separator row is gone', () => {
    expect(markdownToText('|Model|Recall@10|\n|---|---|\n|BM25|0.61|')).toBe('Model Recall@10\nBM25 0.61')
  })

  test('Given superscript tags, inline code and a link, Then only their text remains', () => {
    expect(markdownToText('### _Token_ <sup>1</sup> Limits use `bm25` and [the code](https://example.org).')).toBe(
      'Token 1 Limits use bm25 and the code.',
    )
  })

  test('Given bullet and numbered lists, Then bullets are dropped and item numbers are kept', () => {
    expect(markdownToText('- [1] Robertson. BM25.\n- [2] Sparck Jones.\n\n3. Third step\n4. Fourth step')).toBe(
      '[1] Robertson. BM25.\n[2] Sparck Jones.\n\n3. Third step\n4. Fourth step',
    )
  })

  test('Given plain text with soft line breaks, Then it is unchanged', () => {
    expect(markdownToText('plain text\nacross lines')).toBe('plain text\nacross lines')
  })
})
