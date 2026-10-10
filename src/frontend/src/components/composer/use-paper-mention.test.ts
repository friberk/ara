import { act, renderHook } from '@testing-library/react'
import type { Paper } from '@/api/types'
import type { Mention } from './Composer'
import { usePaperMention } from './use-paper-mention'

const paper = { id: 'p2', title: 'Dense passage retrieval', authors: ['Vladimir Karpukhin'], year: 2020, venue: 'EMNLP' } as Paper
const handle = (): Mention => ({ insert: vi.fn(), refocus: vi.fn() })

test('Given a pick, When the next @ opens the picker before the first one has finished closing, Then the late close changes nothing', () => {
  const { result } = renderHook(() => usePaperMention({ selected: [] }))
  const first = handle()
  act(() => result.current.onMention(first))
  act(() => result.current.picker.onSelect(paper))
  expect(first.insert).toHaveBeenCalledWith({ id: 'p2', label: 'Dense passage retrieval', paper: { authors: ['Vladimir Karpukhin'], year: 2020, venue: 'EMNLP' } })
  act(() => result.current.picker.onOpenChange(false))
  // Radix hands back focus after its exit animation, with the handler of that render.
  const lateClose = result.current.picker.refocus!
  const second = handle()
  act(() => result.current.onMention(second))
  act(() => lateClose())
  expect(first.refocus).not.toHaveBeenCalled()
  expect(second.refocus).not.toHaveBeenCalled()
  expect(result.current.picker.open).toBe(true)
  expect(result.current.picker.mentioning).toBe(true)
})

test('Given a picker opened by typing @, When it closes without a pick, Then the caret goes back to the question', () => {
  const { result } = renderHook(() => usePaperMention({ selected: [] }))
  const typed = handle()
  act(() => result.current.onMention(typed))
  act(() => result.current.picker.onOpenChange(false))
  act(() => result.current.picker.refocus!())
  expect(typed.refocus).toHaveBeenCalledTimes(1)
  expect(typed.insert).not.toHaveBeenCalled()
})
