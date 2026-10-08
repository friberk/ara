import { cn } from '@/lib/utils'
import { authorLine } from './paper-format'

/** Authors and year as separate spaced items; a shortened author list keeps the full list in its tooltip. */
export function PaperByline({ authors, year, children, className }: { authors?: string[] | null; year?: number | null; children?: React.ReactNode; className?: string }) {
  const line = authorLine(authors)
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground', className)}>
      {line?.truncated ? (
        <>
          <span aria-hidden="true" title={line.full}>{line.short}</span>
          <span className="sr-only">{line.full}</span>
        </>
      ) : (
        <span>{line?.short ?? 'Authors unknown'}</span>
      )}
      <span className="tabular">{year ?? 'Year unknown'}</span>
      {children}
    </div>
  )
}
