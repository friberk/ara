import type { Paper } from '@/api/types'

/**
 * Whether questions can be asked now. locked: the paper has no readable PDF, so the field is disabled.
 * reason: the footnote that explains a lock or an unusable model. waiting: models are still loading.
 */
export type QuestionGate = { locked: boolean; reason: string | null; waiting: boolean }

export function questionGate(paper: Paper, model: { usable: boolean; loading: boolean; pdfComing?: boolean; localForSeveral?: boolean; pdfRemoved?: 'only' | 'one of several' }): QuestionGate {
  // A PDF the chat is pinned to was removed (ARA-097): its answers still read, but it cannot be searched again.
  if (model.pdfRemoved === 'only') return { locked: true, reason: 'The PDF this conversation used was removed. Start a new conversation to ask more.', waiting: false }
  if (model.pdfRemoved) return { locked: true, reason: 'A PDF this conversation used was removed. Remove that paper from the conversation to ask more.', waiting: false }
  // The PDF is on its way: automatic retrieval is bringing it, or it is being read (ARA-086).
  if (paper.document_status === 'processing' || (paper.document_status === 'metadata_only' && model.pdfComing)) return { locked: true, reason: 'You can ask questions once the PDF is ready.', waiting: false }
  if (paper.document_status === 'failed') return { locked: true, reason: 'PDF processing failed. Attach a text-based PDF to ask questions.', waiting: false }
  if (paper.document_status !== 'ready' || !paper.active_document_id) return { locked: true, reason: 'Attach a PDF to ask questions about this paper.', waiting: false }
  if (model.loading) return { locked: false, reason: null, waiting: true }
  if (!model.usable) return { locked: false, reason: 'The selected model can’t answer questions. Choose another model.', waiting: false }
  // Open models are frozen (ARA-090), so a chat over several papers answers with hosted models only (ARA-088).
  if (model.localForSeveral) return { locked: false, reason: 'Chats over several papers need a hosted model. Choose one below.', waiting: false }
  return { locked: false, reason: null, waiting: false }
}
export const canAsk = (gate: QuestionGate) => !gate.locked && !gate.reason && !gate.waiting
