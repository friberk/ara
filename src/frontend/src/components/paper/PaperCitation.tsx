import type { Paper } from '@/api/types'
import { citationLine } from '@/lib/paper-names'
import { cn } from '@/lib/utils'

/**
 * A paper's short citation in APA/Harvard style from what it has: "Han et al. (2018), *USENIX Security Symposium*",
 * "Han et al. (2018)", "Han et al., *Venue*", "2018, *Venue*" or a single part; nothing when it has none. Only the
 * italic venue truncates, with its full name in a tooltip, so authors and year stay visible. On a highlighted picker row
 * the text darkens to keep 4.5:1 (citation-contrast.test.ts).
 */
export function PaperCitation({ paper, className, wrap = false }: { paper: Pick<Paper, 'authors' | 'year'> & { venue?: string | null }; className?: string; wrap?: boolean }) {
  const { authors, year, venue } = citationLine(paper)
  if (!authors && !year && !venue) return null
  const lead = authors || year
  // `wrap` sets it as running text, where a long venue wraps instead of truncating (the ⓘ sheet, ARA-097).
  if (wrap) {
    return (
      <span className={cn('text-xs text-pretty text-muted-foreground', className)}>
        {authors}
        {authors && year && ' ('}
        {year && <span className="tabular">{year}</span>}
        {authors && year && ')'}
        {lead && venue && ', '}
        {venue && <cite className="italic">{venue}</cite>}
      </span>
    )
  }
  return (
    <span className={cn('flex min-w-0 items-baseline text-xs text-muted-foreground group-data-selected/command-item:text-foreground/70', className)}>
      {lead && (
        <span className="shrink-0 whitespace-nowrap">
          {authors}
          {authors && year && ' ('}
          {year && <span className="tabular">{year}</span>}
          {authors && year && ')'}
          {venue && ',\u00a0'}
        </span>
      )}
      {venue && <cite className="min-w-0 truncate pr-[0.15em] italic" title={venue}>{venue}</cite>}
    </span>
  )
}
