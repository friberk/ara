import type { Citation } from '@/api/types'
import { Button } from '@/components/ui/button'

export type CitationChipProps = { citation: Citation; onSelect?: (citation: Citation) => void; className?: string }

/** Contract stub (lead): a page button. ARA-035 adds the inline style and the excerpt preview. */
export function CitationChip({ citation, onSelect, className }: CitationChipProps) {
  return <Button type="button" size="xs" variant="outline" className={className} onClick={() => onSelect?.(citation)}>Page {citation.page}</Button>
}
