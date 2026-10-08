import type { Paragraph, PhrasingContent, Root } from 'mdast'
import { remarkCitations } from './remark-citations'

const a = '11111111-1111-4111-8111-111111111111'
const b = '22222222-2222-4222-8222-222222222222'
const unknown = '99999999-9999-4999-8999-999999999999'

function transform(children: PhrasingContent[], allowed = [a, b]) {
  const paragraph: Paragraph = { type: 'paragraph', children }
  const tree: Root = { type: 'root', children: [paragraph] }
  remarkCitations({ allowed: new Set(allowed) })(tree)
  return paragraph.children
}
const text = (value: string): PhrasingContent => ({ type: 'text', value })
const chip = (chunkId: string) => ({ type: 'citationMarker', chunkId, data: { hName: 'cite', hProperties: { dataChunkId: chunkId } } })

test('Given a marker for a known chunk, Then it becomes a citation node where it was written', () => {
  expect(transform([text(`Attention replaces recurrence [source:${a}]. It also parallelises.`)])).toMatchObject([
    text('Attention replaces recurrence'), chip(a), text('. It also parallelises.'),
  ])
})

test('Given unknown markers, Then they disappear with the space before them', () => {
  expect(transform([text(`The claim [source:${unknown}] holds [source:${unknown}].`)])).toEqual([text('The claim holds.')])
})

test('Given repeated markers in one run, Then each chunk appears once and order is kept', () => {
  expect(transform([text(`Shown [source:${a}][source:${a}] [source:${b}] [source:${unknown}] [source:${a}].`)])).toMatchObject([
    text('Shown'), chip(a), chip(b), text('.'),
  ])
})

test('Given the same chunk cited in separate sentences, Then each sentence keeps its chip', () => {
  expect(transform([text(`One [source:${a}]. Two [source:${a}].`)])).toMatchObject([text('One'), chip(a), text('. Two'), chip(a), text('.')])
})

test('Given uppercase hex, Then the marker resolves to the lowercase chunk; other spellings stay text', () => {
  expect(transform([text(`Upper [source:${a.toUpperCase()}].`)])).toMatchObject([text('Upper'), chip(a), text('.')])
  const literal = `[SOURCE:${a}] and [source:not-a-uuid] stay.`
  expect(transform([text(literal)])).toEqual([text(literal)])
})

test('Given a marker inside link text, Then it is removed without nesting a chip in the link', () => {
  const children = transform([{ type: 'link', url: 'https://example.org', children: [text(`the paper [source:${a}]`)] }])
  expect(children).toEqual([{ type: 'link', url: 'https://example.org', children: [text('the paper')] }])
})

test('Given markers inside emphasis, Then the chip stays inside that emphasis', () => {
  expect(transform([{ type: 'emphasis', children: [text(`key point [source:${b}]`)] }])).toMatchObject([
    { type: 'emphasis', children: [text('key point'), chip(b)] },
  ])
})
