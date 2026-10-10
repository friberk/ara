import { createContext, useContext } from 'react'
import type { Citation, Paper } from '@/api/types'

/**
 * Contract between the conversation pane and the reader (owned by the lead; ARA-036/ARA-037).
 *
 * - Citation chips call showSource(citation, claim). The reader scrolls to citation.page of citation.document_id
 *   (which may be an earlier PDF than the paper's active document) and highlights the sentences of
 *   citation.excerpt that support claim, the text the chip stands after; without a claim it highlights the excerpt.
 * - On narrow screens showSource also switches the view to 'pdf'.
 * - sourceRequest changes identity on every call (nonce), so clicking the same chip twice re-runs the jump.
 */
export type WorkspaceView = 'chat' | 'pdf'
export type SourceRequest = { citation: Citation; claim?: string; nonce: number }
/** 'region': the text was not found but the stored layout boxes were outlined; 'page-only': neither was possible. */
export type HighlightOutcome = 'highlighted' | 'region' | 'page-only'

export type WorkspaceContextValue = {
  paper: Paper
  /** Current narrow-screen view. Desktop shows reader and conversation together and ignores it. */
  view: WorkspaceView
  setView: (view: WorkspaceView) => void
  sourceRequest: SourceRequest | null
  showSource: (citation: Citation, claim?: string) => void
  /** The reader reports whether the excerpt was found in the text layer (or its boxes outlined), so the UI can say so. */
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
