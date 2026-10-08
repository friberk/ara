import { render, screen } from '@testing-library/react'
import { ToggleGroup, ToggleGroupItem } from './toggle-group'

test('Given a single-choice toggle group, Then assistive technology sees a radio group of its options', () => {
  render(<ToggleGroup type="single" aria-label="Theme" defaultValue="dark"><ToggleGroupItem value="light">Light</ToggleGroupItem><ToggleGroupItem value="dark">Dark</ToggleGroupItem></ToggleGroup>)
  const group = screen.getByRole('radiogroup', { name: 'Theme' })
  expect(group).toBeVisible()
  expect(screen.getByRole('radio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true')
})

test('Given a multiple-choice toggle group, Then it is a toolbar, not a radio group', () => {
  render(<ToggleGroup type="multiple" aria-label="Formats"><ToggleGroupItem value="bold">Bold</ToggleGroupItem></ToggleGroup>)
  expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
  expect(screen.getByRole('toolbar', { name: 'Formats' })).toBeVisible()
})
