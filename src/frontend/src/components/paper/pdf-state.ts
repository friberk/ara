import type { DocumentState } from '@/api/types'

/** The tooltip and screen-reader text for each PDF state; the @ picker reuses it to explain a blocked row. */
export const pdfStateLabels: Record<DocumentState, string> = { ready: 'PDF attached', metadata_only: 'No PDF yet', processing: 'Preparing PDF…', failed: 'PDF couldn’t be read' }
