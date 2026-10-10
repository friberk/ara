import { act, render, renderHook, screen } from '@testing-library/react'
import { ThreadLayout } from './ThreadLayout'
import { useFollowBottom } from './use-follow-bottom'

// Finish review: content scrolled under the conversation header was sliced mid-line, so the viewport faded its top edge.
// ARA-097: that fade made scrolled text look as if it showed through the paper chips above it. While the thread is
// scrolled away from its top, the header now ends at an opaque row and a hairline instead.

function element(scrollTop: number) {
  const node = document.createElement('div')
  Object.defineProperties(node, { scrollTop: { value: scrollTop, writable: true }, scrollHeight: { value: 2000 }, clientHeight: { value: 500 } })
  return node
}

test('Given the thread is scrolled down, Then the hook reports it; back at the top it does not', () => {
  const { result } = renderHook(() => useFollowBottom('a'))
  const node = element(300)
  ;(result.current.scrollRef as { current: HTMLDivElement | null }).current = node
  act(() => result.current.onScroll())
  expect(result.current.scrolled).toBe(true)
  node.scrollTop = 0
  act(() => result.current.onScroll())
  expect(result.current.scrolled).toBe(false)
})

test('Given a scrolled thread, Then a hairline divides it from the header and nothing fades into the chips; at the top neither shows', () => {
  const { rerender } = render(<ThreadLayout scrollRef={{ current: null }} onScroll={() => {}} away={false} scrolled onLatest={() => {}} composer={null}>content</ThreadLayout>)
  const region = screen.getByRole('region', { name: 'Conversation' })
  expect(region).toHaveAttribute('data-scrolled', 'true')
  expect(region.parentElement).toHaveClass('border-t', 'data-scrolled:border-border')
  expect(region.parentElement).toHaveAttribute('data-scrolled', 'true')
  expect(region.className).not.toMatch(/mask-image/)
  rerender(<ThreadLayout scrollRef={{ current: null }} onScroll={() => {}} away={false} scrolled={false} onLatest={() => {}} composer={null}>content</ThreadLayout>)
  expect(screen.getByRole('region', { name: 'Conversation' })).not.toHaveAttribute('data-scrolled')
  expect(screen.getByRole('region', { name: 'Conversation' }).parentElement).not.toHaveAttribute('data-scrolled')
})
