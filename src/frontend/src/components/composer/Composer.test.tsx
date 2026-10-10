import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Composer, type ComposerProps } from './Composer'

function Harness(props: Partial<ComposerProps> & { onSend?: (value: string) => void }) {
  const [value, setValue] = useState(props.value ?? '')
  return (
    <TooltipProvider>
      <Composer label="Question about this paper" placeholder="Ask a question" submitLabel="Ask question" {...props} value={value} onValueChange={setValue} onSubmit={() => props.onSend?.(value)} />
    </TooltipProvider>
  )
}

test('Given text, When Enter is pressed, Then the composer submits it; Shift+Enter adds a line instead', async () => {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<Harness onSend={onSend} />)
  const input = screen.getByRole('textbox', { name: 'Question about this paper' })
  await user.type(input, 'line one{Shift>}{Enter}{/Shift}line two')
  expect(onSend).not.toHaveBeenCalled()
  await user.keyboard('{Enter}')
  expect(onSend).toHaveBeenCalledWith('line one\nline two')
})

test('Given blank text, Then neither Enter nor the send button submits', async () => {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<Harness onSend={onSend} />)
  await user.type(screen.getByRole('textbox', { name: 'Question about this paper' }), '   {Enter}')
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
  expect(onSend).not.toHaveBeenCalled()
})

test('Given an IME composition, When Enter confirms a character, Then it does not submit', () => {
  const onSend = vi.fn()
  render(<Harness value="日本" onSend={onSend} />)
  const input = screen.getByRole('textbox', { name: 'Question about this paper' })
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, isComposing: true }))
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

test('Given a disabled composer, Then the field is disabled and the footnote explains why', () => {
  render(<Harness value="Why?" disabled footnote="Attach the PDF to ask questions." header={<span>Context chip</span>} leading={<button type="button">Attach</button>} trailing={<button type="button">Model</button>} />)
  expect(screen.getByRole('textbox', { name: 'Question about this paper' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled()
  expect(screen.getByText('Attach the PDF to ask questions.')).toBeVisible()
  for (const name of ['Attach', 'Model']) expect(screen.getByRole('button', { name })).toBeVisible()
  expect(screen.getByText('Context chip')).toBeVisible()
})

test('Given a mention handler, When @ starts a word, Then it opens the paper picker instead of typing; an email address types normally', async () => {
  const onMention = vi.fn()
  const user = userEvent.setup()
  render(<Harness onMention={onMention} />)
  const input = screen.getByRole('textbox', { name: 'Question about this paper' })
  await user.type(input, '@')
  expect(onMention).toHaveBeenCalledTimes(1)
  expect(input).toHaveValue('')
  await user.type(input, 'Compare with @')
  expect(onMention).toHaveBeenCalledTimes(2)
  expect(input).toHaveValue('Compare with ')
  await user.type(input, 'ada@example.org')
  expect(onMention).toHaveBeenCalledTimes(2)
  expect(input).toHaveValue('Compare with ada@example.org')
})
