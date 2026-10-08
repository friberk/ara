import { Skeleton } from '@/components/ui/skeleton'

/** Page-shaped placeholders while pdf.js or the document loads. */
export function PagesSkeleton() {
  return (
    <div role="status" aria-label="Loading PDF" className="flex h-full w-full flex-col items-center gap-4 overflow-hidden bg-muted p-4">
      <Skeleton className="aspect-[8.5/11] w-full max-w-3xl shrink-0 bg-card" />
      <Skeleton className="aspect-[8.5/11] w-full max-w-3xl shrink-0 bg-card" />
    </div>
  )
}
