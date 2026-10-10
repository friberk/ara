// The composer is a TipTap editor (ARA-096). userEvent types into it through ProseMirror's DOM observer. Carets are
// placed with the editor's own commands (editorOf, deletePill) because jsdom has no layout for arrow keys or clicks, and
// keys next to a pill are dispatched as keydown events for ProseMirror's keymap, as a browser would.
import { createRef, useState } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { DraftMention } from '@/lib/mentions'
import { deletePill, draftIn, editorOf, isEditable, textIn } from '@/test/editor'
import { Composer, type ComposerProps, type Mention, type MentionTarget } from './Composer'

const title = 'Dense passage retrieval'
const dense = { id: 'p2', label: title, paper: { authors: ['Vladimir Karpukhin', 'Barlas Oguz'], year: 2020, venue: 'EMNLP' } }
const citation = 'Karpukhin & Oguz (2020), EMNLP'

type HarnessProps = Partial<ComposerProps> & { onSend?: (text: string, mentions: DraftMention[]) => void }

function Harness({ onSend, value = '', mentions = [], ...props }: HarnessProps) {
  const [draft, setDraft] = useState({ text: value, mentions: [...mentions] })
  return (
    <TooltipProvider>
      <Composer label="Question about this paper" placeholder="Ask a question" submitLabel="Ask question" leading={<button type="button">Toolbar</button>} {...props} value={draft.text} mentions={draft.mentions} onValueChange={(text, next) => setDraft({ text, mentions: next })} onSubmit={() => onSend?.(draft.text, draft.mentions)} />
      <button type="button" onClick={() => setDraft({ text: '', mentions: [] })}>Clear</button>
    </TooltipProvider>
  )
}

function field() { return screen.getByRole('textbox', { name: 'Question about this paper' }) }

/** Types "Compare @" and returns the handle the composer gave its @ listener. */
async function startMention(user: ReturnType<typeof userEvent.setup>, onMention = vi.fn<(mention: Mention) => void>()) {
  await user.type(field(), 'Compare @')
  await waitFor(() => expect(onMention).toHaveBeenCalledTimes(1))
  return onMention.mock.calls[0]![0]
}

test('Given text, When Enter is pressed, Then the composer submits it; Shift+Enter adds a line instead', async () => {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<Harness onSend={onSend} />)
  await user.type(field(), 'line one{Shift>}{Enter}{/Shift}line two')
  expect(onSend).not.toHaveBeenCalled()
  await user.keyboard('{Enter}')
  expect(onSend).toHaveBeenCalledWith('line one\nline two', [])
})

test('Given blank text, Then neither Enter nor the send button submits', async () => {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<Harness onSend={onSend} />)
  await user.type(field(), '   {Enter}')
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
  expect(onSend).not.toHaveBeenCalled()
})

test('Given an IME composition, When Enter confirms a character, Then it does not submit', () => {
  const onSend = vi.fn()
  render(<Harness value="日本" onSend={onSend} />)
  fireEvent.keyDown(field(), { key: 'Enter', keyCode: 13, isComposing: true })
  fireEvent.compositionStart(field())
  fireEvent.keyDown(field(), { key: 'Enter', keyCode: 13 })
  expect(onSend).not.toHaveBeenCalled()
})

test('Given a running generation, Then Stop replaces send and calls onStop', async () => {
  const onStop = vi.fn()
  const user = userEvent.setup()
  render(<Harness value="Why?" busy onStop={onStop} />)
  expect(screen.queryByRole('button', { name: 'Ask question' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Stop generation' }))
  expect(onStop).toHaveBeenCalledTimes(1)
})

test('Given a disabled composer, Then the field cannot be edited and the footnote explains why', () => {
  render(<Harness value="Why?" disabled footnote="Attach the PDF to ask questions." header={<span>Context chip</span>} leading={<button type="button">Attach</button>} trailing={<button type="button">Model</button>} />)
  expect(isEditable(field())).toBe(false)
  expect(field()).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
  expect(screen.getByText('Attach the PDF to ask questions.')).toBeVisible()
  for (const name of ['Attach', 'Model']) expect(screen.getByRole('button', { name })).toBeVisible()
  expect(screen.getByText('Context chip')).toBeVisible()
})

test('Given the composer, Then it is a labelled multi-line textbox that announces its placeholder', () => {
  render(<Harness />)
  expect(field()).toHaveAttribute('aria-multiline', 'true')
  expect(field()).toHaveAttribute('aria-placeholder', 'Ask a question')
  expect(isEditable(field())).toBe(true)
})

test('Given a mention handler, When @ starts a word, Then the picker opens; an email address types normally', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  await user.type(field(), '@')
  await waitFor(() => expect(onMention).toHaveBeenCalledTimes(1))
  await user.type(field(), ' then ada@example.org')
  expect(onMention).toHaveBeenCalledTimes(1)
  expect(textIn(field())).toBe('@ then ada@example.org')
})

test('Given @ typed, When a paper is picked, Then an atomic pill with its title replaces the @ and the draft records its code-point span', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  await user.type(field(), '🔬 ')
  const mention = await startMention(user, onMention)
  act(() => mention.insert(dense))
  // React draws the pill a moment after the editor inserts it.
  const pill = await within(field()).findByRole('group', { name: title })
  expect(pill).toHaveAttribute('aria-roledescription', 'paper')
  expect(pill).toHaveAccessibleDescription(citation)
  expect(pill).toHaveTextContent(title)
  // One code point for the emoji, as the server counts.
  expect(draftIn(field())).toEqual({ text: `🔬 Compare ${title} `, mentions: [{ paper_id: 'p2', label: title, start: 10, end: 33, paper: dense.paper }] })
  await user.type(field(), 'please')
  expect(textIn(field())).toBe(`🔬 Compare ${title} please`)
})

test('Given the picker closes without a pick, Then the typed @ stays as text and the caret returns after it', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  const mention = await startMention(user, onMention)
  act(() => mention.refocus())
  await waitFor(() => expect(field()).toHaveFocus())
  await user.keyboard('home')
  expect(textIn(field())).toBe('Compare @home')
  expect(onMention).toHaveBeenCalledTimes(1)
})

for (const [key, side] of [['Backspace', 'after'], ['Delete', 'before']] as const) {
  test(`Given the caret ${side} a pill, When ${key} is pressed, Then the pill is removed as one unit`, async () => {
    const onMention = vi.fn()
    const user = userEvent.setup()
    render(<Harness onMention={onMention} />)
    const mention = await startMention(user, onMention)
    act(() => mention.insert(dense))
    deletePill(field(), 0, key)
    expect(draftIn(field())).toEqual({ text: 'Compare  ', mentions: [] })
  })
}

test('Given a selection over pills, When it is deleted or cut, Then the pills go with it', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  const mention = await startMention(user, onMention)
  act(() => mention.insert(dense))
  await user.keyboard('{Control>}a{/Control}{Backspace}')
  expect(draftIn(field())).toEqual({ text: '', mentions: [] })

  await user.type(field(), 'Again @')
  await waitFor(() => expect(onMention).toHaveBeenCalledTimes(2))
  act(() => onMention.mock.calls[1]![0].insert(dense))
  act(() => { editorOf(field()).commands.selectAll() })
  fireEvent.cut(field(), { clipboardData: { clearData: () => {}, setData: () => {}, getData: () => '' } })
  expect(draftIn(field())).toEqual({ text: '', mentions: [] })
})

test('Given text on the clipboard, When it is pasted, Then only its plain text arrives, with line breaks', () => {
  render(<Harness />)
  act(() => { editorOf(field()).commands.focus() })
  fireEvent.paste(field(), { clipboardData: { types: ['text/plain', 'text/html'], getData: (type: string) => (type === 'text/plain' ? 'first\nsecond' : '<b>first</b><p>second</p>') } })
  expect(textIn(field())).toBe('first\nsecond')
  expect(field().querySelector('b, strong')).toBeNull()
})

test('Given a length limit, Then typing and pasting stop at it and a pill that would overflow is not inserted', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} maxLength={20} />)
  const mention = await startMention(user, onMention)
  act(() => mention.insert(dense))
  // "Compare " and the pill with its space would be 32 characters.
  expect(draftIn(field())).toEqual({ text: 'Compare @', mentions: [] })
  fireEvent.paste(field(), { clipboardData: { types: ['text/plain'], getData: () => 'abcdefghijklmnop' } })
  expect(textIn(field())).toBe('Compare @abcdefghijk')
  await user.type(field(), 'z')
  expect(textIn(field())).toBe('Compare @abcdefghijk')
})

test('Given a draft set from outside, Then the editor shows it with its pills, and clearing empties it', async () => {
  const user = userEvent.setup()
  render(<Harness value={`See ${title} now`} mentions={[{ paper_id: 'p2', label: title, start: 4, end: 27, paper: dense.paper }]} />)
  expect(await within(field()).findByRole('group', { name: title })).toHaveAccessibleDescription(citation)
  expect(textIn(field())).toBe(`See ${title} now`)
  await user.click(screen.getByRole('button', { name: 'Clear' }))
  expect(draftIn(field())).toEqual({ text: '', mentions: [] })
})

test('Given a pill, When its remove button is pressed, Then the pill and its space go, as with Backspace, and the editor keeps focus', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  const mention = await startMention(user, onMention)
  act(() => mention.insert(dense))
  await user.type(field(), 'differ?')
  const pill = await within(field()).findByRole('group', { name: title })
  await user.hover(pill)
  const remove = within(pill).getByRole('button', { name: `Remove ${title}` })
  expect(fireEvent.mouseDown(remove)).toBe(false)
  fireEvent.click(remove)
  expect(draftIn(field())).toEqual({ text: 'Compare differ?', mentions: [] })
  expect(field()).toHaveFocus()
})

test('Given a pill selected from the keyboard, Then it shows its remove button, and Backspace removes it', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  const mention = await startMention(user, onMention)
  act(() => mention.insert(dense))
  act(() => { editorOf(field()).commands.setNodeSelection(9) })
  const pill = await within(field()).findByRole('group', { name: title })
  await waitFor(() => expect(pill).toHaveAttribute('data-active', 'true'))
  expect(within(pill).getByRole('button', { name: `Remove ${title}` })).toBeInTheDocument()
  fireEvent.keyDown(field(), { key: 'Backspace' })
  expect(draftIn(field()).mentions).toEqual([])
})

test('Given the @ button, When a paper is chosen, Then the pill goes at the caret the question had, or at the end if it had none', async () => {
  const user = userEvent.setup()
  const target = createRef<MentionTarget>()
  render(<Harness value="Compare with BM25" mentionTarget={target} />)
  // Never focused: the end, after a space.
  act(() => target.current!.insert(dense))
  expect(textIn(field())).toBe(`Compare with BM25 ${title} `)
  await user.click(screen.getByRole('button', { name: 'Clear' }))
  await user.type(field(), 'Compare with BM25')
  // The caret after "Compare ", then the toolbar takes focus, as the @ button does.
  act(() => { editorOf(field()).commands.setTextSelection(9) })
  await user.click(screen.getByRole('button', { name: 'Toolbar' }))
  act(() => target.current!.insert(dense))
  expect(draftIn(field())).toMatchObject({ text: `Compare ${title} with BM25`, mentions: [{ paper_id: 'p2', start: 8, end: 31 }] })
})
