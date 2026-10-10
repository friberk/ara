import { useLayoutEffect, useRef, useState } from 'react'

const followDistance = 80

/**
 * Keeps the thread pinned to its newest content while the reader is within 80px of the bottom.
 * Scrolling up to reread releases it; sending a question or "Scroll to latest" pins it again.
 * `signal` changes whenever the thread grows (a message, a streamed delta).
 */
export function useFollowBottom(signal: string) {
  const ref = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const [away, setAway] = useState(false)
  // Scrolled away from the top: a hairline divides the thread from the header and the paper chips (ARA-097).
  const [scrolled, setScrolled] = useState(false)
  useLayoutEffect(() => {
    const element = ref.current
    if (element && following.current) {
      element.scrollTop = element.scrollHeight
      setScrolled(element.scrollTop > 0)
    }
  }, [signal])
  function onScroll() {
    const element = ref.current
    if (!element) return
    const near = element.scrollHeight - element.scrollTop - element.clientHeight < followDistance
    following.current = near
    setAway(!near)
    setScrolled(element.scrollTop > 0)
  }
  function stick() {
    following.current = true
    setAway(false)
    const element = ref.current
    if (element) element.scrollTop = element.scrollHeight
  }
  function toLatest() {
    following.current = true
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }
  return { scrollRef: ref, onScroll, away, scrolled, stick, toLatest }
}
