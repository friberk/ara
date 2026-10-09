import type { Paragraph, PhrasingContent, Root } from 'mdast'
import { remarkCitations } from './remark-citations'

const a = '11111111-1111-4111-8111-111111111111'
const b = '22222222-2222-4222-8222-222222222222'
const c = '33333333-3333-4333-8333-333333333333'
const unknown = '99999999-9999-4999-8999-999999999999'
const known = new Set([a, b, c])

function transformAll(paragraphs: PhrasingContent[][], allowed: ReadonlySet<string> = known) {
  const tree: Root = { type: 'root', children: paragraphs.map((children): Paragraph => ({ type: 'paragraph', children })) }
  remarkCitations({ allowed })(tree)
  return tree.children.map((paragraph) => (paragraph as Paragraph).children)
}
const transform = (children: PhrasingContent[], allowed?: ReadonlySet<string>) => transformAll([children], allowed)[0]!
const text = (value: string): PhrasingContent => ({ type: 'text', value })
const chip = (chunkId: string, claim?: string) => ({ type: 'citationMarker', chunkId, data: { hName: 'cite', hProperties: claim === undefined ? { dataChunkId: chunkId } : { dataChunkId: chunkId, dataClaim: claim } } })
const nowrap = (...children: unknown[]) => ({ type: 'citationGroup', children, data: { hName: 'span', hProperties: { className: ['whitespace-nowrap'] } } })

/** The marker sequence with nowrap groups unwrapped and neighbouring text joined, for tests about resolution only. */
function flat(nodes: PhrasingContent[]): PhrasingContent[] {
  const out: PhrasingContent[] = []
  for (const node of nodes.flatMap((child) => ((child.type as string) === 'citationGroup' ? (child as unknown as { children: PhrasingContent[] }).children : [child]))) {
    const last = out.at(-1)
    if (node.type === 'text' && last?.type === 'text') out[out.length - 1] = text(last.value + node.value)
    else out.push('children' in node ? { ...node, children: flat(node.children as PhrasingContent[]) } as PhrasingContent : node)
  }
  return out
}

test('Given a marker for a known chunk, Then it becomes a citation node where it was written', () => {
  expect(flat(transform([text(`Attention replaces recurrence [source:${a}]. It also parallelises.`)]))).toMatchObject([
    text('Attention replaces recurrence'), chip(a), text('. It also parallelises.'),
  ])
})

test('Given unknown markers, Then they disappear with the space before them', () => {
  expect(transform([text(`The claim [source:${unknown}] holds [source:${unknown}].`)])).toEqual([text('The claim holds.')])
})

test('Given repeated markers in one run, Then each chunk appears once and order is kept', () => {
  expect(flat(transform([text(`Shown [source:${a}][source:${a}] [source:${b}] [source:${unknown}] [source:${a}].`)]))).toMatchObject([
    text('Shown'), chip(a), chip(b), text('.'),
  ])
})

test('Given two passages from one page in a run, Then each passage keeps its own chip (ARA-075)', () => {
  expect(flat(transform([text(`Both [source:${b}] [source:${c}] [source:${a}].`)]))).toMatchObject([text('Both'), chip(b), chip(c), chip(a), text('.')])
})

test('Given the same chunk cited in separate sentences, Then each sentence keeps its chip', () => {
  expect(flat(transform([text(`One [source:${a}]. Two [source:${a}].`)]))).toMatchObject([text('One'), chip(a), text('. Two'), chip(a), text('.')])
})

test('Given uppercase hex, Then the marker resolves to the lowercase chunk; other spellings stay text', () => {
  expect(flat(transform([text(`Upper [source:${a.toUpperCase()}].`)]))).toMatchObject([text('Upper'), chip(a), text('.')])
  const literal = `[SOURCE:${a}] and [source:not-a-uuid] stay.`
  expect(transform([text(literal)])).toEqual([text(literal)])
})

test('Given a marker inside link text, Then it is removed without nesting a chip in the link', () => {
  const children = transform([{ type: 'link', url: 'https://example.org', children: [text(`the paper [source:${a}]`)] }])
  expect(children).toEqual([{ type: 'link', url: 'https://example.org', children: [text('the paper')] }])
})

test('Given markers inside emphasis, Then the chip stays inside that emphasis', () => {
  expect(flat(transform([{ type: 'emphasis', children: [text(`key point [source:${b}]`)] }]))).toMatchObject([
    { type: 'emphasis', children: [text('key point'), chip(b)] },
  ])
})

describe('claims (test-first)', () => {
  test('Given a marker, Then it records the text from the previous sentence boundary as the claim it supports', () => {
    expect(flat(transform([text(`Intro sentence. Attention replaces recurrence [source:${a}]. It also parallelises.`)]))).toMatchObject([
      text('Intro sentence. Attention replaces recurrence'), chip(a, 'Attention replaces recurrence'), text('. It also parallelises.'),
    ])
  })

  test('Given a marker after the full stop, Then the claim is that whole sentence', () => {
    const [, marker] = flat(transform([text(`Intro sentence! Heads capture syntax. [source:${a}]`)]))
    expect(marker).toMatchObject(chip(a, 'Heads capture syntax.'))
  })

  test('Given emphasis, code and math inside the sentence, Then the claim is their plain text', () => {
    const children = transform([
      text('Is it new? It presents '), { type: 'strong', children: [text('self-attention')] }, text(' and '),
      { type: 'emphasis', children: [text('multi-head')] }, text(' attention with '), { type: 'inlineCode', value: 'd_k' },
      text(` scaling [source:${a}].`),
    ])
    expect(JSON.stringify(children)).toContain('"dataClaim":"It presents self-attention and multi-head attention with d_k scaling"')
  })

  test('Given a run of markers, Then every chip in it shares one claim', () => {
    expect(flat(transform([text(`Shown here [source:${a}] [source:${b}].`)]))).toMatchObject([text('Shown here'), chip(a, 'Shown here'), chip(b, 'Shown here'), text('.')])
  })

  test('Given a claim at the start of a paragraph, Then the previous paragraph is not part of it', () => {
    const [, second] = transformAll([[text('An earlier paragraph without a full stop')], [text(`It scores 28.4 BLEU [source:${a}].`)]])
    expect(flat(second!)).toMatchObject([text('It scores 28.4 BLEU'), chip(a, 'It scores 28.4 BLEU'), text('.')])
  })
})

describe('nowrap grouping (test-first)', () => {
  test('Given a chip after a word, Then the word, the chip and the punctuation after it share one nowrap span', () => {
    expect(transform([text(`Attention replaces recurrence [source:${a}]. It also parallelises.`)])).toMatchObject([
      text('Attention replaces '), nowrap(text('recurrence'), chip(a), text('.')), text(' It also parallelises.'),
    ])
  })

  test('Given consecutive chips, Then they join the last word in one span', () => {
    expect(transform([text(`Both approaches. [source:${b}] [source:${a}] Next.`)])).toEqual([
      text('Both '), nowrap(text('approaches.'), chip(b, 'Both approaches.'), chip(a, 'Both approaches.')), text(' Next.'),
    ])
  })

  test('Given the last word is emphasised, Then only that word moves into the span, still emphasised', () => {
    expect(transform([{ type: 'strong', children: [text('multi-head attention')] }, text(` [source:${a}].`)])).toMatchObject([
      { type: 'strong', children: [text('multi-head ')] }, nowrap({ type: 'strong', children: [text('attention')] }, chip(a), text('.')),
    ])
  })

  test('Given a chip with no word before it, Then nothing is grouped', () => {
    expect(transform([text(`[source:${a}] opens the paragraph.`)])).toEqual([chip(a), text(' opens the paragraph.')])
  })
})
