import { createContext, useContext } from 'react'
import type { Citation, Paper } from '@/api/types'

/**
 * Contract between the conversation pane and the reader (owned by the lead; ARA-036/ARA-037).
 *
 * - Citation chips call showSource(citation). The reader scrolls to citation.page of citation.document_id
 *   (which may be an earlier PDF than the paper's active document) and highlights citation.excerpt.
 * - On narrow screens showSource also switches the view to 'pdf'.
 * - sourceRequest changes identity on every call (nonce), so clicking the same chip twice re-runs the jump.
 */
export type WorkspaceView = 'chat' | 'pdf' | 'details'
export type SourceRequest = { citation: Citation; nonce: number }
export type HighlightOutcome = 'highlighted' | 'page-only'

export type WorkspaceContextValue = {
  paper: Paper
  /** Current narrow-screen view. Desktop shows reader and conversation together and ignores it. */
  view: WorkspaceView
  setView: (view: WorkspaceView) => void
  /** Reader tab on desktop: the PDF or the paper details. */
  readerTab: 'pdf' | 'details'
  setReaderTab: (tab: 'pdf' | 'details') => void
  sourceRequest: SourceRequest | null
  showSource: (citation: Citation) => void
  /** The reader reports whether the excerpt was found in the text layer, so the UI can say so. */
  highlightOutcome: HighlightOutcome | null
  reportHighlight: (outcome: HighlightOutcome) => void
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function useWorkspace() {
  const context = useContext(WorkspaceContext)
  if (!context) throw new Error('useWorkspace must be used inside the paper workspace.')
  return context
}

/** For components that also render outside the workspace (for example in tests). */
export function useOptionalWorkspace() { return useContext(WorkspaceContext) }
