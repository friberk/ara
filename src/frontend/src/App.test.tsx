import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'

test('research shell offers the required workspace navigation', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
  expect(screen.getByRole('navigation', { name: 'Workspace' })).toBeVisible()
  for (const name of ['Search', 'Library', 'Jobs', 'Settings']) expect(screen.getByRole('link', { name })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Find your next paper' })).toBeVisible()
})
