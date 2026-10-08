import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProviderSwitcher } from './ProviderSwitcher'

test('Given the provider menu, When Semantic Scholar is chosen, Then the change is reported and the name says the current provider', async () => {
  const onChange = vi.fn()
  const user = userEvent.setup()
  const { rerender } = render(<ProviderSwitcher value="openalex" onChange={onChange} />)
  await user.click(screen.getByRole('button', { name: 'Academic provider: OpenAlex' }))
  expect(await screen.findByRole('menuitemradio', { name: /OpenAlex/ })).toHaveAttribute('aria-checked', 'true')
  await user.click(screen.getByRole('menuitemradio', { name: /Semantic Scholar/ }))
  expect(onChange).toHaveBeenCalledWith('semantic_scholar')
  rerender(<ProviderSwitcher value="semantic_scholar" onChange={onChange} />)
  expect(screen.getByRole('button', { name: 'Academic provider: Semantic Scholar' })).toBeVisible()
})
