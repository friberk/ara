import type { ChatSummary, Paper } from '@/api/types'

/** The PDF this chat pinned for this paper, which a newer upload does not replace. */
export const usesEarlierPdf = (paper: Paper, chat: ChatSummary) => chat.papers.some((included) => included.paper_id === paper.id && included.document_id !== paper.active_document_id)
