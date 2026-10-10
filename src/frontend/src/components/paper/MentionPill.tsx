import { usePaper } from '@/hooks/queries/papers'
import type { MentionSpan } from '@/lib/mentions'
import { PaperPill } from './PaperPill'

/**
 * A paper a sent question mentioned, as the same pill the composer showed but without its remove button, on the paper
 * tone so it stands apart from the bubble (ARA-096).
 * It reads its label as sent; the paper, once loaded, gives the citation card and description.
 */
export function MentionPill({ mention }: { mention: MentionSpan }) {
  const paper = usePaper(mention.paper_id).data
  return <PaperPill title={mention.label} paper={paper} surface="paper" />
}
