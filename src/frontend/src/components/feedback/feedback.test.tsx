import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FileText } from 'lucide-react'
import { ErrorNotice } from './ErrorNotice'
import { LoadingState } from './LoadingState'
import { EmptyState } from './EmptyState'
import { DocumentStatusBadge } from './DocumentStatusBadge'

test('Given an error, Then one inline alert shows its message and offers a retry', async () => {
  const retry = vi.fn()
  render(<ErrorNotice error={new Error('Provider is busy. Try again later.')} retry={retry} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Provider is busy. Try again later.')
  await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
  expect(retry).toHaveBeenCalledTimes(1)
})

test('Given no error or a non-Error value, Then nothing renders or a generic recovery message appears', () => {
  const { rerender } = render(<ErrorNotice error={null} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  rerender(<ErrorNotice error="boom" />)
  expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong. Try again.')
  expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
})

test('Given loading and empty states, Then loading is announced and the empty state names what is missing and what to do', () => {
  render(<><LoadingState>Loading your library…</LoadingState><EmptyState icon={FileText} title="Your library is empty" action={<button type="button">Upload a PDF</button>}>Search for a paper or upload one.</EmptyState></>)
  expect(screen.getByRole('status')).toHaveTextContent('Loading your library…')
  expect(screen.getByRole('heading', { name: 'Your library is empty', level: 2 })).toBeVisible()
  expect(screen.getByText('Search for a paper or upload one.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Upload a PDF' })).toBeVisible()
})

test('Given each document state, Then the badge uses the reader-facing label', () => {
  const { rerender } = render(<DocumentStatusBadge state="metadata_only" />)
  expect(screen.getByText('PDF needed')).toBeVisible()
  for (const [state, label] of [['processing', 'Preparing PDF'], ['ready', 'Ready to read'], ['failed', 'Processing failed']] as const) {
    rerender(<DocumentStatusBadge state={state} />)
    expect(screen.getByText(label)).toBeVisible()
  }
})
