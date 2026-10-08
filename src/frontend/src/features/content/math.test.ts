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

  test('Given display math over several lines, Then each line stays on its own line between fences', () => {
    expect(normalizeMath('\\[\n  \\text{Attention}(Q, K, V) =\n  \\operatorname{softmax}(QK^T)V\n\\]')).toBe('$$\n\\text{Attention}(Q, K, V) =\n\\operatorname{softmax}(QK^T)V\n$$')
  })

  test('Given an aligned environment with a % comment, Then its line breaks survive so the comment ends at its line', () => {
    expect(normalizeMath('\\[\n\\begin{aligned}\na &= b \\\\ % first row\nc &= d\n\\end{aligned}\n\\]')).toBe('$$\n\\begin{aligned}\na &= b \\\\ % first row\nc &= d\n\\end{aligned}\n$$')
  })

  test('Given multi-line display math in a list item or quote, Then every line keeps the container prefix', () => {
    expect(normalizeMath('- Loss:\n  \\[\n  L = a % weight\n  + b\n  \\]')).toBe('- Loss:\n  $$\n  L = a % weight\n  + b\n  $$')
    expect(normalizeMath('> \\[\n> a = b \\\\\n> c = d\n> \\]')).toBe('> $$\n> a = b \\\\\n> c = d\n> $$')
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

  // Test-after (ARA-035 audit): these branches shipped before a test covered them.
  test('Given display math wrapped across quoted lines, Then the quote markers are not read as TeX', () => {
    expect(normalizeMath('> \\[\n> a = b\n> \\]')).toBe('> $$\n> a = b\n> $$')
  })

  test('Given math that starts or ends with a dollar, Then padding keeps the fence from growing', () => {
    expect(normalizeMath('Escaped \\(\\$\\) sign.')).toBe('Escaped $$ \\$ $$ sign.')
  })

  test('Given display math in a heading, Then it stays inline so the heading survives', () => {
    expect(normalizeMath('## Cost \\[O(n)\\]')).toBe('## Cost $$O(n)$$')
  })

  test('Given a backtick line whose info contains a backtick, Then it is a code span, not a fence', () => {
    expect(normalizeMath('```js`x```\n\\(y\\)')).toBe('```js`x```\n$$y$$')
  })

  test('Given an indented code block, Then LaTeX delimiters inside it are untouched', () => {
    expect(normalizeMath('Example:\n\n    print("\\(x\\)")\n    \\[y\\]\n\nThen \\(z\\).')).toBe('Example:\n\n    print("\\(x\\)")\n    \\[y\\]\n\nThen $$z$$.')
    expect(normalizeMath('\tcode \\(x\\)')).toBe('\tcode \\(x\\)')
    expect(normalizeMath('Text\n\n    a \\(x\\)\n\n    b \\(y\\)\n\nBack \\(z\\)')).toBe('Text\n\n    a \\(x\\)\n\n    b \\(y\\)\n\nBack $$z$$')
  })

  test('Given indented lines that continue a list or paragraph, Then they are not code and still convert', () => {
    expect(normalizeMath('- Item\n\n    Continued \\(x\\)')).toBe('- Item\n\n    Continued $$x$$')
    expect(normalizeMath('1. Step\n    - nested \\(x\\)')).toBe('1. Step\n    - nested $$x$$')
    expect(normalizeMath('Text\n    lazy \\(x\\)')).toBe('Text\n    lazy $$x$$')
  })
})
