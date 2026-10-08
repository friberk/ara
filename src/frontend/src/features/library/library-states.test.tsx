// Test-after coverage (ARA-038): these behaviours shipped before their tests. Each test was checked
// against a deliberate mutation of the implementation to confirm it can fail.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'
import { json, mockApi } from '@/test/fetch-routes'
import { testClient } from '@/test/render'

const paper = (index: number) => ({ id: `p${index}`, title: `Paper ${index}`, authors: ['Ada Researcher'], year: 2024, abstract: null, doi: null, sources: [], document_status: 'ready', active_document_id: `d${index}`, metadata_provenance: {} })
afterEach(() => vi.unstubAllGlobals())

function History() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output aria-label="Location">{`${location.pathname}${location.search}${location.hash}`}</output>
      <button type="button" onClick={() => navigate(-1)}>History back</button>
      <button type="button" onClick={() => navigate(1)}>History forward</button>
    </>
  )
}
function mount(entries: string[], index = entries.length - 1) {
  const user = userEvent.setup()
  render(<QueryClientProvider client={testClient()}><MemoryRouter initialEntries={entries} initialIndex={index}><App /><History /></MemoryRouter></QueryClientProvider>)
  return { user }
}
function deferred() {
  let resolve: (response: Response) => void = () => {}
  const promise = new Promise<Response>((done) => { resolve = done })
  return { promise, resolve }
}

test('Given the library is loading, Then skeleton rows are announced', async () => {
  mockApi({ 'GET /papers': () => new Promise<Response>(() => {}) })
  mount(['/library'])
  await waitFor(() => expect(screen.getAllByRole('status').some((element) => element.textContent?.includes('Loading your library…'))).toBe(true))
  const status = screen.getAllByRole('status').find((element) => element.textContent?.includes('Loading your library…')) as HTMLElement
  expect(status.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThanOrEqual(3)
})

test('Given a full first page, When Load more is pressed, Then it is disabled and busy until the next papers arrive', async () => {
  const next = deferred()
  mockApi({ 'GET /papers': ({ url }) => (url.searchParams.get('offset') === '20' ? next.promise : json({ items: Array.from({ length: 20 }, (_, index) => paper(index)) })) })
  const { user } = mount(['/library'])
  const main = screen.getByRole('main')
  const more = await within(main).findByRole('button', { name: 'Load more' })
  expect(within(main).getByText('20+ papers')).toBeVisible()
  await user.click(more)
  await waitFor(() => expect(more).toBeDisabled())
  expect(more).toHaveAttribute('aria-busy', 'true')
  next.resolve(json({ items: [paper(20)] }))
  expect(await within(main).findByRole('link', { name: 'Paper 20' })).toBeVisible()
  expect(within(main).getByText('21 papers')).toBeVisible()
  expect(within(main).queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

test('Given filtered library entries in history, When going back and forward, Then the filter field and request follow the URL', async () => {
  const { calls } = mockApi({})
  const { user } = mount(['/library?q=graphs', '/library?q=attention'])
  const filter = await screen.findByRole('searchbox', { name: 'Filter library' })
  expect(filter).toHaveValue('attention')
  await user.click(screen.getByRole('button', { name: 'History back' }))
  await waitFor(() => expect(filter).toHaveValue('graphs'))
  await waitFor(() => expect(calls.some((call) => call.path === '/papers' && call.url.searchParams.get('q') === 'graphs')).toBe(true))
  // The debounced writer must not push the old text back over the URL the user navigated to.
  await new Promise((resolve) => setTimeout(resolve, 400))
  expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/library\?q=graphs$/)
  await user.click(screen.getByRole('button', { name: 'History forward' }))
  await waitFor(() => expect(filter).toHaveValue('attention'))
})

test('Given the library cannot load, Then the error is shown inline and Try again reloads it', async () => {
  // Only the library list (limit 20) fails, and keeps failing until the user retries; the sidebar's short list loads normally.
  let failing = true
  mockApi({ 'GET /papers': ({ url }) => (url.searchParams.get('limit') === '20' && failing ? json({ code: 'DATABASE_UNAVAILABLE', message: 'The library is unavailable right now.', request_id: 'r1' }, 503) : json({ items: [paper(1)] })) })
  const { user } = mount(['/library'])
  const main = screen.getByRole('main')
  const alert = await within(main).findByRole('alert')
  expect(alert).toHaveTextContent('The library is unavailable right now.')
  failing = false
  await user.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(await within(main).findByRole('link', { name: 'Paper 1' })).toBeVisible()
  expect(within(main).queryByRole('alert')).not.toBeInTheDocument()
})

test('Given saved titles with hidden characters, Then rows render them clean', async () => {
  mockApi({ 'GET /papers': { items: [{ ...paper(1), title: 'Exploiting input\u0007 sanitization', abstract: 'Web services\u0000 sanitize input.' }] } })
  mount(['/library'])
  const main = screen.getByRole('main')
  expect(await within(main).findByRole('link', { name: 'Exploiting input sanitization' })).toHaveAttribute('href', '/papers/p1')
  expect(within(main).getByText('Web services sanitize input.')).toBeVisible()
})

test('Given Load more fails, Then the loaded papers stay and Try again fetches the next page', async () => {
  let failing = true
  mockApi({
    'GET /papers': ({ url }) => {
      if (url.searchParams.get('offset') !== '20') return json({ items: Array.from({ length: 20 }, (_, index) => paper(index)) })
      return failing ? json({ code: 'DATABASE_UNAVAILABLE', message: 'More papers are unavailable right now.', request_id: 'r1' }, 503) : json({ items: [paper(20)] })
    },
  })
  const { user } = mount(['/library'])
  const main = screen.getByRole('main')
  await user.click(await within(main).findByRole('button', { name: 'Load more' }))
  const alert = await within(main).findByRole('alert')
  expect(alert).toHaveTextContent('More papers are unavailable right now.')
  expect(within(main).getByRole('link', { name: 'Paper 0' })).toBeVisible()
  expect(within(main).queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  failing = false
  await user.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(await within(main).findByRole('link', { name: 'Paper 20' })).toBeVisible()
  expect(within(main).queryByRole('alert')).not.toBeInTheDocument()
})
