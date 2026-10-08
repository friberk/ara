import { normalizeMath } from './math'

describe('normalizeMath', () => {
  test('Given \\( \\) delimiters, Then they become inline $$ math in the same sentence', () => {
    expect(normalizeMath('Self-attention costs \\(O(n^2 \\cdot d)\\) per layer.')).toBe('Self-attention costs $$O(n^2 \\cdot d)$$ per layer.')
  })

  test('Given \\[ \\] on its own line, Then $$ fences sit on their own lines', () => {
    expect(normalizeMath('Energy:\n\n\\[E = mc^2\\]\n\nDone.')).toBe('Energy:\n\n$$\nE = mc^2\n$$\n\nDone.')
  })

  test('Given \\[ \\] inside a sentence, Then the display block is split out of the paragraph', () => {
    expect(normalizeMath('Scaled by \\[ \\frac{1}{\\sqrt{d_k}} \\] before the softmax.')).toBe('Scaled by\n$$\n\\frac{1}{\\sqrt{d_k}}\n$$\nbefore the softmax.')
  })

  test('Given display math over several lines, Then the content is kept on one line between fences', () => {
    expect(normalizeMath('\\[\n  \\text{Attention}(Q, K, V) =\n  \\operatorname{softmax}(QK^T)V\n\\]')).toBe('$$\n\\text{Attention}(Q, K, V) = \\operatorname{softmax}(QK^T)V\n$$')
  })

  test('Given display math in a list item or quote, Then the fences keep the container indentation', () => {
    expect(normalizeMath('- Scores:\n  \\[ s = QK^T \\]\n- Next')).toBe('- Scores:\n  $$\n  s = QK^T\n  $$\n- Next')
    expect(normalizeMath('> Note \\[x\\]')).toBe('> Note\n> $$\n> x\n> $$')
  })

  test('Given display math in a table row, Then it stays inline so the table survives', () => {
    expect(normalizeMath('| a | \\[x^2\\] |')).toBe('| a | $$x^2$$ |')
  })

  test('Given fenced or inline code, Then LaTeX delimiters inside it are untouched', () => {
    const fenced = '```python\nprint("\\(x\\)")\n\\[y\\]\n```\nThen \\(z\\).'
    expect(normalizeMath(fenced)).toBe('```python\nprint("\\(x\\)")\n\\[y\\]\n```\nThen $$z$$.')
    expect(normalizeMath('Use `\\(x\\)` or ``a ` \\[b\\]`` literally, but \\(c\\).')).toBe('Use `\\(x\\)` or ``a ` \\[b\\]`` literally, but $$c$$.')
    expect(normalizeMath('~~~\n\\(x\\)\n~~~')).toBe('~~~\n\\(x\\)\n~~~')
  })

  test('Given escaped backslashes and LaTeX line breaks, Then only real delimiters convert', () => {
    expect(normalizeMath('A path C:\\\\(tmp\\\\) stays.')).toBe('A path C:\\\\(tmp\\\\) stays.')
    expect(normalizeMath('\\[ a \\\\ b \\]')).toBe('$$\na \\\\ b\n$$')
  })

  test('Given unclosed or paragraph-crossing delimiters, Then the text is left alone', () => {
    expect(normalizeMath('Streaming \\(x + ')).toBe('Streaming \\(x + ')
    expect(normalizeMath('\\(a\n\nb\\)')).toBe('\\(a\n\nb\\)')
  })

  test('Given math that contains dollar runs, Then the fence is longer than any run inside', () => {
    expect(normalizeMath('\\(\\$$5\\)')).toBe('$$$\\$$5$$$')
  })

  test('Given plain currency and existing $$ math, Then nothing changes', () => {
    expect(normalizeMath('Costs $5 and $10, and $$x$$ stays.')).toBe('Costs $5 and $10, and $$x$$ stays.')
  })
})
