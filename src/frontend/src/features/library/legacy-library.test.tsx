// Legacy behaviour tests moved from pages/workflows.test.tsx (ARA-033). The feature owner replaces them
// with tests for the redesigned UI while keeping the same behavioural coverage.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'

function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function mount(path: string) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>); return client }
afterEach(() => vi.unstubAllGlobals())


test('Given a PDF upload accepted, Then the durable processing status is shown', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/documents') && init?.method === 'POST') return response({ paper_id: 'p1', document_id: 'd1', job_id: 'j1' }, 202)
    if (url.endsWith('/jobs/j1')) return response({ id: 'j1', kind: 'ingest', state: 'processing', stage: 'extracting', progress: 40, attempts: 1, error: null, result: null })
    return response({ items: [] })
  }))
  mount('/library'); const user = userEvent.setup()
  await user.upload(await screen.findByLabelText('PDF file'), new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
  expect(await screen.findByText(/extracting/)).toBeVisible()
  await waitFor(() => expect(screen.getByRole('link', { name: 'Open uploaded paper' })).toHaveAttribute('href', '/papers/p1'))
})


test('Given an oversized PDF, Then upload stays disabled with a recoverable explanation', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ items: [] }))); mount('/library')
  const file = new File(['%PDF'], 'large.pdf', { type: 'application/pdf' }); Object.defineProperty(file, 'size', { value: 26 * 1024 * 1024 })
  await userEvent.setup().upload(await screen.findByLabelText('PDF file'), file)
  expect(screen.getByRole('alert')).toHaveTextContent('exceeds 25 MB')
  expect(screen.getByRole('button', { name: 'Upload PDF' })).toBeDisabled()
})

