import { render, screen } from '@testing-library/react'
import { GeneratedContent } from './GeneratedContent'
test('Given model Markdown, Then readable structure is rendered without executable HTML or unsafe links', () => {
  const { container } = render(<GeneratedContent content={'## Results\n\n**Grounded** answer.\n\n[Unsafe](javascript:alert(1))\n\n<script>window.attack = true</script>\n\n<img src="x" onerror="window.attack = true">'}/>)
  expect(screen.getByRole('heading', { name: 'Results' })).toBeVisible()
  expect(screen.getByText('Grounded')).toHaveProperty('tagName', 'STRONG')
  expect(container.querySelector('script')).toBeNull()
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
})

test('Given source markers, Then only valid backend UUID markers are hidden and prose remains', () => {
  const source = '12345678-1234-1234-1234-123456789abc'
  const content = `The result is supported[source:${source}].\n\n[source:not-a-uuid] remains visible. [SOURCE:${source}] also remains visible.`
  const { container } = render(<GeneratedContent content={content}/>)
  expect(screen.getByText('The result is supported.')).toBeVisible()
  expect(container).not.toHaveTextContent(`[source:${source}]`)
  expect(container).toHaveTextContent('[source:not-a-uuid] remains visible.')
  expect(container).toHaveTextContent(`[SOURCE:${source}] also remains visible.`)
  expect(content).toContain(`[source:${source}]`)
})
