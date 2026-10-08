import { act, render, renderHook, screen } from '@testing-library/react'
import { ThreadLayout } from './ThreadLayout'
import { useFollowBottom } from './use-follow-bottom'

// Finish review: content scrolled under the conversation header was sliced mid-line.
// While the thread is scrolled away from its top, its viewport fades the top edge instead.

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

test('Given a scrolled thread, Then its viewport is marked to fade its top edge; at the top it is not', () => {
  const { rerender } = render(<ThreadLayout scrollRef={{ current: null }} onScroll={() => {}} away={false} scrolled onLatest={() => {}} composer={null}>content</ThreadLayout>)
  expect(screen.getByRole('region', { name: 'Conversation' })).toHaveAttribute('data-scrolled', 'true')
  rerender(<ThreadLayout scrollRef={{ current: null }} onScroll={() => {}} away={false} scrolled={false} onLatest={() => {}} composer={null}>content</ThreadLayout>)
  expect(screen.getByRole('region', { name: 'Conversation' })).not.toHaveAttribute('data-scrolled')
})
