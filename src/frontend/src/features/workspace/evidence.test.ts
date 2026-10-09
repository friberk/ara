import { findEvidence, selectEvidence } from './evidence'
import { headsClaim, interpretability, page7 } from './evidence.fixtures'
import type { TextItem } from './text-highlight'

const oneLine = (text: string) => text.replace(/\s+/g, ' ').trim()
const chosen = (excerpt: string, claim: string) => selectEvidence(excerpt, claim).map(oneLine)

describe('selectEvidence', () => {
  test('Given the page-7 chunk and the attention-heads claim, Then the interpretability evidence is chosen and the Training text is not', () => {
    const sentences = chosen(page7, headsClaim)
    expect(sentences).toContain(interpretability[2])
    expect(sentences.every((sentence) => interpretability.includes(sentence))).toBe(true)
    expect(sentences.join(' ')).not.toMatch(/train|WMT|GPU|convolution/i)
  })

  test('Given case, punctuation, inflections and numbers, Then they still match while shared stopwords alone do not', () => {
    const excerpt = 'The model is one of the first of its kind. Each head LEARNS syntax-like behavior in the encoder. The big model reaches 28.4 BLEU on the test set.'
    expect(chosen(excerpt, 'Heads learned SYNTAX.')).toEqual(['Each head LEARNS syntax-like behavior in the encoder.'])
    expect(chosen(excerpt, 'It scores 28.4 BLEU.')).toEqual(['The big model reaches 28.4 BLEU on the test set.'])
  })

  test('Given words that recur across the excerpt, Then they count for little against the claim’s rarer words', () => {
    const excerpt = [
      'The large model improves BLEU on WMT 2014.',
      'The base model also improves BLEU on WMT 2014.',
      'Every model is evaluated with BLEU on WMT 2014.',
      'Each model is scored with BLEU on WMT 2014.',
      'Our big ensemble reaches 28.4 BLEU.',
    ].join(' ')
    expect(chosen(excerpt, 'The big ensemble model reaches 28.4 BLEU on WMT 2014.')).toEqual(['Our big ensemble reaches 28.4 BLEU.'])
  })

  test('Given a neighbour scoring at least half the best, Then it joins the passage; one scoring less does not', () => {
    const excerpt = 'Dropout regularises the residual layers. Label smoothing hurts perplexity but improves accuracy and BLEU. It also improves BLEU slightly. The optimizer uses warmup.'
    expect(chosen(excerpt, 'Label smoothing hurts perplexity yet improves accuracy and BLEU.')).toEqual(['Label smoothing hurts perplexity but improves accuracy and BLEU.'])
    expect(chosen(excerpt, 'Label smoothing improves BLEU slightly.')).toEqual(['Label smoothing hurts perplexity but improves accuracy and BLEU.', 'It also improves BLEU slightly.'])
  })

  test('Given qualifying sentences near and far, Then the contiguous neighbour is preferred and at most three are chosen', () => {
    const excerpt = [
      'The schedule follows the original recipe.',
      'The encoder and decoder stacks each use residual connections.',
      'Dropout is applied to the output of each residual sublayer and to the embedding sums in the encoder and decoder.',
      'Training ran on eight GPUs.',
      'Dropout on residual sublayers is applied at a rate of 0.1.',
      'Results are averaged over five runs.',
      'Dropout on embeddings is applied in the encoder and decoder.',
    ].join(' ')
    // The last sentence outscores the neighbour of the best one, but the neighbour keeps the passage contiguous.
    expect(chosen(excerpt, 'Dropout is applied to residual sublayers, embeddings, encoder and decoder stacks at one rate.')).toEqual([
      'The encoder and decoder stacks each use residual connections.',
      'Dropout is applied to the output of each residual sublayer and to the embedding sums in the encoder and decoder.',
      'Dropout on residual sublayers is applied at a rate of 0.1.',
    ])
  })

  test('Given a claim that no sentence supports above the minimal threshold, Then nothing is chosen so the caller marks the whole excerpt', () => {
    expect(selectEvidence(page7, 'The authors thank their colleagues for comments.')).toEqual([])
    expect(selectEvidence(page7, '')).toEqual([])
    expect(selectEvidence('', headsClaim)).toEqual([])
  })

  test('Given sentences and headings across line breaks, Then each chosen sentence is returned verbatim from the excerpt', () => {
    const [sentence] = selectEvidence(page7, headsClaim)
    expect(page7).toContain(sentence)
    expect(sentence).toMatch(/^Not only do individual attention\nheads/)
  })
})

describe('findEvidence', () => {
  /** One pdf.js text item per printed line, as the text layer renders a simple single-column page. */
  const lines = (...rows: string[]): TextItem[] => rows.map((str) => ({ str, hasEOL: true }))
  const page = lines(
    '4 Why Self-Attention',
    'Convolutional layers are generally more expensive than',
    'recurrent layers. As side benefit, self-attention could yield',
    'more interpretable models. We inspect attention distributions',
    'from our models. Not only do individual attention',
    'heads clearly learn to perform different tasks, many appear',
    'to exhibit behavior related to the syntactic and semantic',
    'structure of the sentences.',
    '5 Training',
    'This section describes the training regime for our models.',
  )
  const excerpt = page.slice(1).map((item) => item.str).join('\n')
  const whole = (item: number, rows: TextItem[] = page) => ({ item, start: 0, end: rows[item]!.str.length })
  const all = [1, 2, 3, 4, 5, 6, 7, 8, 9].map((item) => whole(item))

  test('Given a claim whose sentence begins mid-line, Then the strong mark starts at that sentence, not at the start of the printed line', () => {
    expect(findEvidence(page, excerpt, headsClaim)).toEqual({
      strong: [{ item: 4, start: page[4]!.str.indexOf('Not only'), end: page[4]!.str.length }, whole(5), whole(6), whole(7)],
      context: [1, 2, 3, 8, 9],
    })
  })

  test('Given no claim, Then the whole excerpt is strong, as before claims existed', () => {
    expect(findEvidence(page, excerpt)).toEqual({ strong: all, context: [] })
    expect(findEvidence(page, excerpt, '')).toEqual({ strong: all, context: [] })
  })

  test('Given a claim no sentence supports, Then the whole excerpt is strong', () => {
    expect(findEvidence(page, excerpt, 'The authors thank their colleagues for comments.')).toEqual({ strong: all, context: [] })
  })

  test('Given the supporting sentence is missing from the text layer, Then the whole located excerpt is strong', () => {
    const imageOnly = page.map((item, index) => (index >= 4 && index <= 7 ? { ...item, str: '' } : item))
    expect(findEvidence(imageOnly, excerpt, headsClaim)).toEqual({ strong: [1, 2, 3, 4, 5, 6, 7, 8, 9].map((item) => whole(item, imageOnly)), context: [] })
  })

  test('Given an excerpt that is not on the page, Then nothing is marked', () => {
    expect(findEvidence(page, 'The measured answer accuracy in this synthetic experiment is 86 percent.', 'Accuracy is 86 percent.')).toEqual({ strong: [], context: [] })
  })

  // Stored chunks are layout Markdown since ARA-071; the text layer never prints its markup.
  const fixturePage = lines('Traceable Research Systems', 'Ada Researcher', '2024', '', 'Abstract', 'A synthetic evaluation of a retrieval-first research assistant using the Orion-12 dataset.')

  test('Given a short Markdown heading chunk, Then its printed lines are strong', () => {
    expect(findEvidence(fixturePage, '# Traceable Research Systems Ada Researcher\n\n2024').strong.map((range) => range.item)).toEqual([0, 1, 2])
  })

  test('Given a Markdown chunk and a claim, Then the supporting sentence is strong and its heading is context', () => {
    const markdown = '# **Abstract**\n\nA synthetic evaluation of a _retrieval-first_ research assistant using the Orion-12 dataset.'
    expect(findEvidence(fixturePage, markdown, 'It evaluates a retrieval-first assistant on the Orion-12 dataset.')).toEqual({
      strong: [whole(5, fixturePage)],
      context: [4],
    })
  })

  test('Given a Markdown table chunk, Then its cells are found without the pipes and separator row', () => {
    const cells = lines('Model', 'Recall@10', 'BM25', '0.61')
    expect(findEvidence(cells, '|Model|Recall@10|\n|---|---|\n|BM25|0.61|').strong.map((range) => range.item)).toEqual([0, 1, 2, 3])
  })
})
