import { useEffect, useId, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/** Clamped to three lines; Show more appears only when the text actually overflows. */
export function ClampedText({ text, className, textClassName }: { text: string; className?: string; textClassName?: string }) {
  const id = useId()
  const ref = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element || expanded) return
    // ResizeObserver reports once on observe, then on every width change (sidebar, window, font load).
    const observer = new ResizeObserver(() => setOverflowing(element.scrollHeight > element.clientHeight + 1))
    observer.observe(element)
    return () => observer.disconnect()
  }, [expanded, text])
  return (
    <div className={className}>
      <p ref={ref} id={id} className={cn('text-sm leading-6 text-pretty text-foreground/80', textClassName, !expanded && 'line-clamp-3')}>{text}</p>
      {(overflowing || expanded) && (
        <button type="button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded((open) => !open)} className="mt-1 rounded-sm text-sm font-medium text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50">
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}
