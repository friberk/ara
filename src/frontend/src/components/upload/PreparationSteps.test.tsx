import { render, screen } from '@testing-library/react'
import { PreparationSteps } from './PreparationSteps'
import { preparationSteps } from './preparation'

test('Given the steps change, Then screen readers hear the current step once, not every upload percentage', () => {
  const { rerender } = render(<PreparationSteps steps={preparationSteps({ upload: { progress: 0.1 }, documentStatus: 'metadata_only' })} />)
  const live = screen.getByText('Uploading', { selector: '[aria-live="polite"]' })
  rerender(<PreparationSteps steps={preparationSteps({ upload: { progress: 0.6 }, documentStatus: 'metadata_only' })} />)
  expect(live).toHaveTextContent(/^Uploading$/)
  rerender(<PreparationSteps steps={preparationSteps({ uploaded: true, ingest: { state: 'processing', stage: 'processing', error: null }, documentStatus: 'processing' })} />)
  expect(live).toHaveTextContent(/^Reading pages$/)
  rerender(<PreparationSteps steps={preparationSteps({ documentStatus: 'ready' })} />)
  expect(live).toHaveTextContent(/^Ready$/)
})
