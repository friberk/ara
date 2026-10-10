import type { Paper } from '@/api/types'

/**
 * Whether questions can be asked now. locked: the paper has no readable PDF, so the field is disabled.
 * reason: the footnote that explains a lock or an unusable model. waiting: models are still loading.
 */
export type QuestionGate = { locked: boolean; reason: string | null; waiting: boolean }

export function questionGate(paper: Paper, model: { usable: boolean; loading: boolean; pdfComing?: boolean }): QuestionGate {
  // Automatic retrieval is bringing the PDF (ARA-086).
  if (paper.document_status === 'metadata_only' && model.pdfComing) return { locked: true, reason: 'You can ask questions once the PDF is ready.', waiting: false }
  if (paper.document_status === 'processing') return { locked: true, reason: 'Questions open when the PDF finishes processing.', waiting: false }
  if (paper.document_status === 'failed') return { locked: true, reason: 'PDF processing failed. Attach a text-based PDF to ask questions.', waiting: false }
  if (paper.document_status !== 'ready' || !paper.active_document_id) return { locked: true, reason: 'Attach a PDF to ask questions about this paper.', waiting: false }
  if (model.loading) return { locked: false, reason: null, waiting: true }
  if (!model.usable) return { locked: false, reason: 'The selected model can’t answer questions. Choose another model.', waiting: false }
  return { locked: false, reason: null, waiting: false }
}
export const canAsk = (gate: QuestionGate) => !gate.locked && !gate.reason && !gate.waiting
