import type { DocumentState } from '@/api/types'

export const documentStateLabels: Record<DocumentState, string> = { metadata_only: 'PDF needed', processing: 'Processing PDF', ready: 'Ready to read', failed: 'Processing failed' }
