import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { heldResponse, json, mockApi } from '@/test/fetch-routes'
import { UploadDropzone } from './UploadDropzone'

afterEach(() => vi.unstubAllGlobals())
const job = { id: 'j1', kind: 'ingest', state: 'processing', stage: 'processing', progress: 20, attempts: 1, generation: 1, result: null, error_code: null, error_message: null, error: null, available_at: '2026-10-08T00:00:00Z', created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', paper_id: 'p1', paper_title: null }
const pdf = (name = 'paper.pdf') => new File(['%PDF-1.4 synthetic'], name, { type: 'application/pdf' })
const posts = (calls: { method: string; path: string; body: unknown }[]) => calls.filter((call) => call.method === 'POST' && call.path === '/documents')

test('Given a chosen PDF, Then it uploads at once with live progress and a fresh request id, without a confirm click', async () => {
  let release = () => {}
  const { calls } = mockApi({ 'POST /documents': () => new Promise<Response>((resolve) => { release = () => resolve(json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }, 202)) }), 'GET /jobs/j1': job })
  const onAccepted = vi.fn()
  const { user } = renderWithProviders(<UploadDropzone onAccepted={onAccepted} />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  const steps = await screen.findByRole('list', { name: 'Preparation steps' })
  expect(within(steps).getByText('Uploading')).toBeVisible()
  expect(await within(steps).findByText('50%')).toBeVisible()
  expect(screen.getByText('paper.pdf')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Upload PDF' })).not.toBeInTheDocument()
  release()
  await waitFor(() => expect(onAccepted).toHaveBeenCalledWith({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }))
  const body = posts(calls)[0]?.body as FormData
  expect(body.get('file')).toBeInstanceOf(File)
  expect(String(body.get('request_id'))).toMatch(/^[0-9a-f-]{36}$/)
  expect(body.has('paper_id')).toBe(false)
  expect(screen.queryByText(/in the background/i)).not.toBeInTheDocument()
})

test('Given an existing paper, Then the upload attaches to it and its stages follow the processing job', async () => {
  const { calls } = mockApi({ 'POST /documents': () => json({ paper_id: 'p9', document_id: 'd9', job_id: 'j1', duplicate: false }, 202), 'GET /jobs/j1': job })
  const { user } = renderWithProviders(<UploadDropzone paperId="p9" />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  // The list is replaced when the upload is accepted, so it is found again rather than kept.
  const steps = () => screen.getByRole('list', { name: 'Preparation steps' })
  await waitFor(() => expect(within(steps()).getByText('Reading pages').closest('li')).toHaveAttribute('aria-current', 'step'))
  expect(within(steps()).getByText('Uploaded')).toBeVisible()
  expect((posts(calls)[0]?.body as FormData).get('paper_id')).toBe('p9')
})

test('Given an oversized PDF, Then nothing is sent and the reason explains how to recover', async () => {
  const { calls } = mockApi({})
  const { user } = renderWithProviders(<UploadDropzone />)
  const file = pdf('large.pdf')
  Object.defineProperty(file, 'size', { value: 26 * 1024 * 1024 })
  await user.upload(screen.getByLabelText('PDF file'), file)
  expect(screen.getByRole('alert')).toHaveTextContent('exceeds 25 MB')
  expect(posts(calls)).toHaveLength(0)
  expect(screen.getByLabelText('PDF file')).toBeEnabled()
})

test('Given a file dropped on the zone, Then it uploads like a chosen one', async () => {
  const { calls } = mockApi({ 'POST /documents': () => json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }, 202), 'GET /jobs/j1': job })
  renderWithProviders(<UploadDropzone />)
  const zone = screen.getByText('Drop a PDF here, or choose one').closest('label') as HTMLElement
  fireEvent.drop(zone, { dataTransfer: { files: [pdf('dropped.pdf')], types: ['Files'] } })
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(screen.getByText('dropped.pdf')).toBeVisible()
})

test('Given the server rejects the upload, Then its message is shown and Try again resends the same request', async () => {
  let attempt = 0
  const { calls } = mockApi({ 'POST /documents': () => (++attempt === 1 ? json({ code: 'STORAGE_UNAVAILABLE', message: 'PDF storage is unavailable. Try again shortly.' }, 503) : json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }, 202)), 'GET /jobs/j1': job })
  const onAccepted = vi.fn()
  const { user } = renderWithProviders(<UploadDropzone onAccepted={onAccepted} />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  expect(await screen.findByRole('alert')).toHaveTextContent('PDF storage is unavailable. Try again shortly.')
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(onAccepted).toHaveBeenCalledTimes(1))
  const [first, second] = posts(calls).map((call) => (call.body as FormData).get('request_id'))
  expect(second).toBe(first)
})

test('Given a PDF already in the library, Then the note says so instead of an error', async () => {
  mockApi({ 'POST /documents': () => json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: true }, 202), 'GET /jobs/j1': { ...job, state: 'completed', stage: 'completed', progress: 100 } })
  const onAccepted = vi.fn()
  const { user } = renderWithProviders(<UploadDropzone onAccepted={onAccepted} />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  expect(await screen.findByRole('status')).toHaveTextContent('This PDF is already in your library.')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(onAccepted).toHaveBeenCalledWith(expect.objectContaining({ paper_id: 'p1', duplicate: true }))
})

test('Given a PDF that belongs to another paper, Then the error links to that paper', async () => {
  mockApi({ 'POST /documents': () => json({ code: 'DOCUMENT_ALREADY_ATTACHED', message: 'This PDF belongs to another paper. Open that paper to reconcile it.', details: [{ paper_id: 'p7' }] }, 409) })
  const { user } = renderWithProviders(<UploadDropzone paperId="p1" />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('This PDF is already attached to another paper in your library.')
  expect(within(alert).getByRole('link', { name: 'Open that paper' })).toHaveAttribute('href', '/papers/p7')
})

test('Given an upload in flight, When Cancel is pressed, Then the zone is ready for another file', async () => {
  mockApi({ 'POST /documents': () => new Promise<Response>(() => {}) })
  const { user } = renderWithProviders(<UploadDropzone chooseLabel="Upload PDF" />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  await user.click(await screen.findByRole('button', { name: 'Cancel upload' }))
  expect(await screen.findByRole('button', { name: 'Upload PDF' })).toBeVisible()
  expect(screen.queryByText('paper.pdf')).not.toBeInTheDocument()
})

const acceptedUpload = () => json({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }, 202)
const dropZone = () => screen.getByText('Drop a PDF here, or choose one').closest('label') as HTMLElement

test('Given a file dragged over the zone, Then the browser is told the zone accepts a drop', () => {
  mockApi({})
  renderWithProviders(<UploadDropzone />)
  // A browser only fires drop on an element whose dragover was default-prevented; fireEvent returns false when it was.
  expect(fireEvent.dragOver(dropZone(), { dataTransfer: { types: ['Files'] } })).toBe(false)
})

test('Given a dropped file, Then it is sent exactly like a chosen one, to the same paper and callback', async () => {
  const { calls } = mockApi({ 'POST /documents': acceptedUpload, 'GET /jobs/j1': job })
  const onAccepted = vi.fn()
  renderWithProviders(<UploadDropzone paperId="p9" onAccepted={onAccepted} />)
  fireEvent.drop(dropZone(), { dataTransfer: { files: [pdf('dropped.pdf'), pdf('ignored.pdf')], types: ['Files'] } })
  await waitFor(() => expect(onAccepted).toHaveBeenCalledWith({ paper_id: 'p1', document_id: 'd1', job_id: 'j1', duplicate: false }))
  expect(posts(calls)).toHaveLength(1)
  const body = posts(calls)[0]?.body as FormData
  expect((body.get('file') as File).name).toBe('dropped.pdf')
  expect(body.get('paper_id')).toBe('p9')
  expect(String(body.get('request_id'))).toMatch(/^[0-9a-f-]{36}$/)
})

test('Given an oversized PDF dropped on the zone, Then it is refused like a chosen one and nothing is sent', async () => {
  const { calls } = mockApi({})
  renderWithProviders(<UploadDropzone />)
  const file = pdf('large.pdf')
  Object.defineProperty(file, 'size', { value: 26 * 1024 * 1024 })
  fireEvent.drop(dropZone(), { dataTransfer: { files: [file], types: ['Files'] } })
  expect(await screen.findByRole('alert')).toHaveTextContent('exceeds 25 MB')
  expect(posts(calls)).toHaveLength(0)
})

test.each([
  ['the picker closed without a file', () => fireEvent.change(screen.getByLabelText('PDF file'), { target: { files: [] } })],
  ['a drop that carries no file', () => fireEvent.drop(dropZone(), { dataTransfer: { files: [], types: ['Files'] } })],
])('Given %s, Then nothing is uploaded and the earlier error stays', async (_case, select) => {
  const { calls } = mockApi({ 'POST /documents': () => json({ code: 'STORAGE_UNAVAILABLE', message: 'PDF storage is unavailable. Try again shortly.' }, 503) })
  const { user } = renderWithProviders(<UploadDropzone />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  expect(await screen.findByRole('alert')).toHaveTextContent('PDF storage is unavailable. Try again shortly.')
  select()
  expect(posts(calls)).toHaveLength(1)
  expect(screen.getByRole('alert')).toHaveTextContent('PDF storage is unavailable. Try again shortly.')
})

test('Given an upload in flight, When Cancel is pressed, Then its transfer is aborted', async () => {
  const upload = heldResponse(acceptedUpload)
  mockApi({ 'POST /documents': upload.handler })
  const { user } = renderWithProviders(<UploadDropzone />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  const cancel = await screen.findByRole('button', { name: 'Cancel upload' })
  expect(upload.aborted()).toBe(false)
  await user.click(cancel)
  expect(upload.aborted()).toBe(true)
})

test('Given a cancelled upload, When the server answers late, Then the paper is not accepted', async () => {
  const upload = heldResponse(acceptedUpload)
  const { calls } = mockApi({ 'POST /documents': upload.handler })
  const onAccepted = vi.fn()
  const { user } = renderWithProviders(<UploadDropzone onAccepted={onAccepted} />)
  await user.upload(screen.getByLabelText('PDF file'), pdf())
  await user.click(await screen.findByRole('button', { name: 'Cancel upload' }))
  await upload.respond()
  expect(onAccepted).not.toHaveBeenCalled()
  expect(screen.queryByText('paper.pdf')).not.toBeInTheDocument()
  expect(calls.some((call) => call.path === '/jobs/j1')).toBe(false)
})
