import { ArrowDown } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** The scrolling thread column with the composer docked beneath it. */
export function ThreadLayout({ scrollRef, onScroll, away, onLatest, composer, children }: {
  scrollRef: React.Ref<HTMLDivElement>
  onScroll: () => void
  /** The reader has scrolled up from the newest content. */
  away: boolean
  onLatest: () => void
  composer: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          role="region"
          aria-label="Conversation"
          tabIndex={0}
          className="absolute inset-0 overflow-y-auto overscroll-contain outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
        >
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 pt-2 pb-10">{children}</div>
        </div>
        {away && (
          <Button type="button" variant="outline" size="icon-sm" onClick={onLatest} aria-label="Scroll to latest message" className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-background shadow-[0_2px_8px_-2px_rgb(0_0_0/0.15)] dark:bg-card">
            <ArrowDown aria-hidden="true" />
          </Button>
        )}
      </div>
      <div className="shrink-0 pb-3">
        <div className="mx-auto w-full max-w-3xl px-4">{composer}</div>
      </div>
    </div>
  )
}
