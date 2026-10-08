import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'

export function testClient() { return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }) }

/** Renders the whole app at a route, with retries off so errors surface immediately. */
export function renderApp(path = '/') {
  const client = testClient()
  const user = userEvent.setup()
  const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
  return { client, user, ...view }
}

/** Renders one component with the query client and router, for focused tests. rerender keeps the providers. */
export function renderWithProviders(ui: React.ReactElement, { path = '/' } = {}) {
  const client = testClient()
  const user = userEvent.setup()
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{children}</MemoryRouter></QueryClientProvider>
  const view = render(ui, { wrapper })
  return { client, user, ...view }
}
