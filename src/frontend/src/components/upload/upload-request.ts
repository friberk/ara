import { ApiError } from '@/api/client'
import type { UploadAccepted } from '@/api/types'

/** An upload failure; `paperId` names the paper that already holds this PDF, when the server says so. */
export class UploadError extends ApiError {
  constructor(message: string, status: number, code?: string, requestId?: string, readonly paperId?: string) { super(message, status, code, requestId); this.name = 'UploadError' }
}

function failure(status: number, text: string): UploadError {
  let body: Record<string, unknown> = {}
  try { const parsed: unknown = JSON.parse(text); if (typeof parsed === 'object' && parsed !== null) body = parsed as Record<string, unknown> } catch { /* not JSON */ }
  const details = Array.isArray(body.details) ? body.details as Record<string, unknown>[] : []
  const owner = details.find((item) => typeof item?.paper_id === 'string')?.paper_id as string | undefined
  const message = body.code === 'DOCUMENT_ALREADY_ATTACHED' ? 'This PDF is already attached to another paper in your library.'
    : typeof body.message === 'string' ? body.message : `Upload failed (${status}). Try again.`
  return new UploadError(message, status, typeof body.code === 'string' ? body.code : undefined, typeof body.request_id === 'string' ? body.request_id : undefined, owner)
}

/**
 * POST /documents through XMLHttpRequest, the only browser API that reports upload progress. Retrying with the same
 * request id replays the original upload instead of creating another.
 */
export function sendPdf(file: File, { requestId, paperId, onProgress, signal }: { requestId: string; paperId?: string; onProgress?: (fraction: number) => void; signal?: AbortSignal }): Promise<UploadAccepted> {
  const body = new FormData()
  body.append('file', file)
  body.append('request_id', requestId)
  if (paperId) body.append('paper_id', paperId)
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', '/api/v1/documents')
    request.upload.onprogress = (event) => { if (event.lengthComputable && event.total > 0) onProgress?.(Math.min(1, event.loaded / event.total)) }
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) { reject(failure(request.status, request.responseText)); return }
      try { resolve(JSON.parse(request.responseText) as UploadAccepted) } catch { reject(failure(request.status, '')) }
    }
    request.onerror = () => reject(new ApiError('Could not reach the server. Check your connection and try again.', 0))
    request.onabort = () => reject(new DOMException('The upload was canceled.', 'AbortError'))
    signal?.addEventListener('abort', () => request.abort(), { once: true })
    request.send(body)
  })
}
