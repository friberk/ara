import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { JobProgress } from './JobProgress'
afterEach(() => vi.unstubAllGlobals())
test('Given a completed job, When the parent rerenders, Then completion is announced once', async () => {
  const job = { id: 'job1', state: 'completed', kind: 'ingest', stage: 'ready', progress: 100, attempts: 1, error: null, result: null }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(job))))
  const settled = vi.fn(); const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = () => <QueryClientProvider client={client}><MemoryRouter><JobProgress jobId="job1" onSettled={(value) => settled(value)}/></MemoryRouter></QueryClientProvider>
  const view = render(ui()); await screen.findByText('Completed'); await waitFor(() => expect(settled).toHaveBeenCalledTimes(1)); view.rerender(ui())
  expect(settled).toHaveBeenCalledTimes(1)
})
