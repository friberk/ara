import type { Citation } from '@/api/types'
import { GeneratedContent } from '@/components/GeneratedContent'

export type MarkdownProps = {
  content: string
  /** Citations of this message or summary. [source:UUID] markers whose UUID is a citation chunk_id become inline chips. */
  citations?: Citation[]
  /** Only citations from this document may render; markers for any other document render nothing. */
  documentId?: string
  /** Called when a reader activates an inline citation chip. */
  onCitation?: (citation: Citation) => void
  className?: string
}

/** Contract stub (lead): safe Markdown without math or inline chips. ARA-035 replaces the internals. */
export function Markdown({ content }: MarkdownProps) {
  return <GeneratedContent content={content} />
}
