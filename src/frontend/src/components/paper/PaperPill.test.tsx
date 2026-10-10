// The paper pill of the composer and of sent questions (ARA-096 follow-up): title, hover ×, citation card.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PaperPill } from './PaperPill'

const title = 'Dense passage retrieval for open-domain question answering'
const dense = { authors: ['Vladimir Karpukhin', 'Barlas Oguz'], year: 2020, venue: 'EMNLP' }

function pill(props: Partial<React.ComponentProps<typeof PaperPill>> = {}) {
  return render(<TooltipProvider><p>Compare <PaperPill title={title} paper={dense} {...props} /> with BM25.</p></TooltipProvider>)
}

test('Given a pill, Then it is named by the title alone, described by its short citation, and shows the title truncated with an icon', () => {
  pill({ onRemove: vi.fn() })
  const group = screen.getByRole('group', { name: title })
  expect(group).toHaveAccessibleDescription('Karpukhin & Oguz (2020), EMNLP')
  expect(group).toHaveAttribute('aria-roledescription', 'paper')
  const label = within(group).getByText(title)
  expect(label).toHaveClass('truncate')
  expect(label).toHaveAttribute('aria-hidden', 'true')
})

test('Given an editable pill, When it is hovered, Then a remove button appears that removes it without taking focus', async () => {
  const onRemove = vi.fn()
  const user = userEvent.setup()
  pill({ onRemove })
  const group = screen.getByRole('group', { name: title })
  expect(within(group).queryByRole('button')).not.toBeInTheDocument()
  await user.hover(group)
  const remove = within(group).getByRole('button', { name: `Remove ${title}` })
  // Pressing it keeps focus where it was (the editor) instead of moving it to the button. user.click would first move
  // the pointer onto the button, which user-event reports to React as leaving the pill, so the press is dispatched.
  expect(fireEvent.mouseDown(remove)).toBe(false)
  fireEvent.click(remove)
  expect(onRemove).toHaveBeenCalledTimes(1)
  await user.unhover(group)
  expect(within(group).queryByRole('button')).not.toBeInTheDocument()
})

test('Given an editable pill selected from the keyboard, Then it shows the remove button and the citation card', async () => {
  pill({ onRemove: vi.fn(), selected: true })
  const group = screen.getByRole('group', { name: title })
  expect(group).toHaveAttribute('data-active', 'true')
  expect(within(group).getByRole('button', { name: `Remove ${title}` })).toBeInTheDocument()
  expect(await screen.findByText('EMNLP')).toBeVisible()
})

test('Given a pill hovered for a moment, Then a card shows its citation, and the full title when the pill cuts it; Escape closes it', async () => {
  const user = userEvent.setup()
  pill({ onRemove: vi.fn() })
  const label = within(screen.getByRole('group', { name: title })).getByText(title)
  Object.defineProperty(label, 'scrollWidth', { configurable: true, value: 400 })
  Object.defineProperty(label, 'clientWidth', { configurable: true, value: 200 })
  await user.hover(label)
  const venue = await screen.findByText('EMNLP')
  const card = venue.closest('[data-slot="hover-card-content"]') as HTMLElement
  expect(card).toHaveTextContent(`${title}Karpukhin & Oguz (2020), EMNLP`)
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByText('EMNLP')).not.toBeInTheDocument())
})

test('Given a paper without authors, year or venue and a title that fits, Then no empty card opens', async () => {
  const user = userEvent.setup()
  pill({ paper: { authors: [], year: null, venue: null } })
  await user.hover(screen.getByRole('img', { name: title }))
  await new Promise((resolve) => setTimeout(resolve, 450))
  expect(document.querySelector('[data-slot="hover-card-content"]')).toBeNull()
})

test('Given a sent question, Then its pill is an image named by the title with no remove button, even when hovered', async () => {
  const user = userEvent.setup()
  pill()
  const image = screen.getByRole('img', { name: title })
  expect(image).toHaveAccessibleDescription('Karpukhin & Oguz (2020), EMNLP')
  await user.hover(image)
  expect(screen.queryByRole('button', { name: `Remove ${title}` })).not.toBeInTheDocument()
  expect(await screen.findByText('EMNLP')).toBeVisible()
})

test('Given a pill inside a question bubble, Then it sits on the paper tone so it stands apart from the bubble', () => {
  render(<TooltipProvider><PaperPill title={title} paper={dense} surface="paper" /></TooltipProvider>)
  const image = screen.getByRole('img', { name: title })
  expect(image).toHaveClass('bg-background')
  expect(image).not.toHaveClass('bg-muted')
})
