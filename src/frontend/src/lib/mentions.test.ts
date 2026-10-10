import { mentionSegments, mentionedPapers, trimDraft, withoutPaper } from './mentions'

const dense = { paper_id: 'p2', label: 'Karpukhin 2020' }
const late = { paper_id: 'p3', label: 'Khattab 2020' }

test('Given a sent question with pills, When history splits it, Then each label at its code-point span becomes a pill', () => {
  // The emoji is one code point, as the server counts, and two UTF-16 units.
  const text = '🔬 Compare Karpukhin 2020 and Khattab 2020'
  const mentions = [{ ...dense, start: 10, end: 24 }, { ...late, start: 29, end: 41 }]
  expect(mentionSegments(text, mentions)).toEqual([{ text: '🔬 Compare ' }, { mention: mentions[0] }, { text: ' and ' }, { mention: mentions[1] }])
  expect(mentionSegments('Plain question', [])).toEqual([{ text: 'Plain question' }])
})

test('Given spans that do not match the text, Then history keeps the text plain', () => {
  expect(mentionSegments('Compare Karpukhin', [{ ...dense, start: 8, end: 22 }])).toEqual([{ text: 'Compare Karpukhin' }])
})

test('Given a draft, When one paper is removed, Then every pill of it goes with its label and one following space, and later pills shift', () => {
  const draft = {
    text: 'Compare Karpukhin 2020 and Khattab 2020 or Karpukhin 2020?',
    mentions: [{ ...dense, start: 8, end: 22 }, { ...late, start: 27, end: 39 }, { ...dense, start: 43, end: 57 }],
  }
  expect(withoutPaper(draft, 'p2')).toEqual({ text: 'Compare and Khattab 2020 or ?', mentions: [{ ...late, start: 12, end: 24 }] })
  expect(mentionedPapers(draft.mentions)).toEqual(['p2', 'p3'])
})

test('Given a draft with surrounding whitespace, When it is sent, Then the text is trimmed and its spans move with it', () => {
  const draft = { text: ' \n Compare Karpukhin 2020  ', mentions: [{ ...dense, start: 11, end: 25 }] }
  expect(trimDraft(draft)).toEqual({ text: 'Compare Karpukhin 2020', mentions: [{ ...dense, start: 8, end: 22 }] })
})
