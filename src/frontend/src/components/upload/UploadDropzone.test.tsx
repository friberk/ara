import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { json, mockApi } from '@/test/fetch-routes'
import { UploadDropzone } from './UploadDropzone'

afterEach(() => vi.unstubAllGlobals())
const job = { id: 'j1', kind: 'ingest', state: 'processing', stage: 'extracting_metadata', progress: 50, attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, available_at: '2026-10-08T00:00:00Z', created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', paper_id: 'p1', paper_title: null }

test('Given a chosen PDF, When Upload PDF is pressed, Then a multipart request with a fresh request id is sent and processing is shown', async () => {
  const { calls } = mockApi({ 'POST /documents': () => json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1' }, 202), 'GET /jobs/j1': job })
  const onAccepted = vi.fn()
  const { user } = renderWithProviders(<UploadDropzone onAccepted={onAccepted} />)
  expect(screen.queryByRole('button', { name: 'Upload PDF' })).not.toBeInTheDocument()
  await user.upload(screen.getByLabelText('PDF file'), new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }))
  expect(screen.getByText('paper.pdf')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  expect(await screen.findByRole('status')).toHaveTextContent('PDF uploaded. Processing continues in the background.')
  expect(await screen.findByText('Extracting title, authors and abstract')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open uploaded paper' })).toHaveAttribute('href', '/papers/p1')
  expect(onAccepted).toHaveBeenCalledWith({ paper_id: 'p1', document_id: 'd1', job_id: 'j1' })
  const body = calls.find((call) => call.method === 'POST')?.body as FormData
  expect(body.get('file')).toBeInstanceOf(File)
  expect(String(body.get('request_id'))).toMatch(/^[0-9a-f-]{36}$/)
  expect(body.has('paper_id')).toBe(false)
})

test('Given an existing paper, Then the upload attaches to it and does not offer to open another paper', async () => {
  const { calls } = mockApi({ 'POST /documents': () => json({ paper_id: 'p9', document_id: 'd9', job_id: 'j1' }, 202), 'GET /jobs/j1': job })
  const { user } = renderWithProviders(<UploadDropzone paperId="p9" />)
  await user.upload(screen.getByLabelText('PDF file'), new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  await screen.findByRole('status')
  expect((calls.find((call) => call.method === 'POST')?.body as FormData).get('paper_id')).toBe('p9')
  expect(screen.queryByRole('link', { name: 'Open uploaded paper' })).not.toBeInTheDocument()
})

test('Given an oversized PDF, Then upload stays disabled with a recoverable explanation', async () => {
  const { calls } = mockApi({})
  const { user } = renderWithProviders(<UploadDropzone />)
  const file = new File(['%PDF'], 'large.pdf', { type: 'application/pdf' })
  Object.defineProperty(file, 'size', { value: 26 * 1024 * 1024 })
  await user.upload(screen.getByLabelText('PDF file'), file)
  expect(screen.getByRole('alert')).toHaveTextContent('exceeds 25 MB')
  expect(screen.getByRole('button', { name: 'Upload PDF' })).toBeDisabled()
  expect(calls).toHaveLength(0)
})

test('Given a file dropped on the zone, Then it is chosen like a picked file and can be removed', async () => {
  mockApi({})
  const { user } = renderWithProviders(<UploadDropzone />)
  const zone = screen.getByText('Drop a PDF here, or choose one').closest('label') as HTMLElement
  fireEvent.drop(zone, { dataTransfer: { files: [new File(['%PDF'], 'dropped.pdf', { type: 'application/pdf' })] } })
  expect(screen.getByText('dropped.pdf')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Remove file' }))
  await waitFor(() => expect(screen.queryByText('dropped.pdf')).not.toBeInTheDocument())
})

test('Given the server rejects the PDF, Then its message is shown inline', async () => {
  mockApi({ 'POST /documents': () => json({ code: 'DOCUMENT_ALREADY_ATTACHED', message: 'This PDF is already attached to another paper.' }, 409) })
  const { user } = renderWithProviders(<UploadDropzone />)
  await user.upload(screen.getByLabelText('PDF file'), new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This PDF is already attached to another paper.')
})
