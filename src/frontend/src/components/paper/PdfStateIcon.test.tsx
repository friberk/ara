import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { DocumentState } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PdfStateIcon } from './PdfStateIcon'

const cases: [DocumentState, string, string][] = [
  ['ready', 'PDF attached', 'lucide-file-text'],
  ['metadata_only', 'No PDF yet', 'lucide-file-question'],
  ['processing', 'Preparing PDF…', 'lucide-loader-circle'],
  ['failed', 'PDF couldn’t be read', 'lucide-file-warning'],
]
const mount = (state: DocumentState, props: { focusable?: boolean } = {}) => render(<TooltipProvider delayDuration={0}><PdfStateIcon state={state} {...props} /></TooltipProvider>)

test.each(cases)('Given the %s state, Then one icon is named "%s" for screen readers', (state, label, iconClass) => {
  const { container } = mount(state)
  expect(screen.getByRole('img', { name: label })).toBeVisible()
  expect(container.querySelector(`svg.${iconClass}`)).not.toBeNull()
  expect(container).not.toHaveTextContent(/Ready to read|PDF needed|Processing failed/)
})

test.each(cases)('Given the %s state, When the icon is hovered, Then the tooltip says "%s"', async (state, label) => {
  mount(state)
  await userEvent.setup().hover(screen.getByRole('img', { name: label }))
  expect(await screen.findByRole('tooltip')).toHaveTextContent(label)
})

test('Given keyboard focus on the icon, Then the tooltip opens', async () => {
  mount('metadata_only')
  await userEvent.setup().tab()
  expect(screen.getByRole('img', { name: 'No PDF yet' })).toHaveFocus()
  expect(await screen.findByRole('tooltip')).toHaveTextContent('No PDF yet')
})

test('Given the icon sits inside a link, Then it is not a tab stop', async () => {
  mount('ready', { focusable: false })
  expect(screen.getByRole('img', { name: 'PDF attached' })).not.toHaveAttribute('tabindex')
})
