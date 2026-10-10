import { useCallback, useMemo } from 'react'
import type { Citation, IncludedPaper } from '@/api/types'
import { usePaperList } from '@/hooks/queries/papers'
import { namedPaper, shortPaperName } from '@/lib/paper-names'

/** What a chat's answers may cite and how their chips name each paper (ARA-088). */
export type ChatSources = {
  /** The chat's pinned PDFs, and the PDFs of papers since removed that earlier answers cite. */
  documents: ReadonlySet<string>
  /** The cited paper's short name, in a chat over several papers or for a paper since removed. */
  paperName?: (citation: Citation) => string | undefined
  /** The citation with its paper, so the reader can open that paper's tab. */
  withPaper: (citation: Citation) => Citation
}

export function useChatSources(papers: readonly IncludedPaper[], citations: readonly Citation[]): ChatSources {
  const byDocument = useMemo(() => new Map(papers.map((paper) => [paper.document_id, paper])), [papers])
  // History keeps citations to papers removed from the chat; the server names their paper.
  const outside = useMemo(() => [...new Set(citations.flatMap((citation) => (citation.paper_id && !byDocument.has(citation.document_id) ? [citation.paper_id] : [])))], [citations, byDocument])
  const fetched = usePaperList(outside)
  const lookup = useMemo(() => new Map(fetched.map((paper) => [paper.id, paper])), [fetched])
  const documents = useMemo(() => new Set([...byDocument.keys(), ...citations.flatMap((citation) => (citation.paper_id && !byDocument.has(citation.document_id) ? [citation.document_id] : []))]), [byDocument, citations])
  // A single-paper chat's citations are the workspace paper's own, so they need no paper.
  const withPaper = useCallback((citation: Citation) => citation.paper_id || papers.length < 2 ? citation : { ...citation, paper_id: byDocument.get(citation.document_id)?.paper_id ?? null }, [byDocument, papers.length])
  const paperName = useCallback((citation: Citation) => {
    const included = byDocument.get(citation.document_id)
    if (included) return papers.length > 1 ? shortPaperName(included) : undefined
    const other = citation.paper_id ? lookup.get(citation.paper_id) : undefined
    return other ? shortPaperName(namedPaper(other)) : undefined
  }, [byDocument, lookup, papers.length])
  return { documents, paperName, withPaper }
}
