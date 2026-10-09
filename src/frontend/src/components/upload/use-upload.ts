import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { UploadAccepted } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'
import { sendPdf } from './upload-request'
import { validatePdf } from './validate-pdf'

export type UploadItem = {
  id: string
  file: File
  /** Kept across retries, so a retry replays the original request instead of starting another. */
  requestId: string
  state: 'uploading' | 'accepted' | 'failed'
  progress: number
  accepted?: UploadAccepted
  error?: Error
  /** The file itself is unusable (wrong type or too large), so retrying cannot help. */
  invalid?: boolean
}

/**
 * Uploads that start as soon as files are chosen or dropped, each with its own progress, result and error. The server
 * deduplicates identical files, and onAccepted runs only while the caller is still mounted.
 */
export function useUploads({ paperId, onAccepted }: { paperId?: string; onAccepted?: (accepted: UploadAccepted, file: File) => void } = {}) {
  const client = useQueryClient()
  const [items, setItems] = useState<UploadItem[]>([])
  const controllers = useRef(new Map<string, AbortController>())
  const mounted = useRef(false)
  const accepted = useRef(onAccepted)
  useEffect(() => { accepted.current = onAccepted })
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  const patch = useCallback((id: string, change: Partial<UploadItem>) => setItems((list) => list.map((item) => (item.id === id ? { ...item, ...change } : item))), [])
  const send = useCallback((item: UploadItem) => {
    const controller = new AbortController()
    controllers.current.set(item.id, controller)
    sendPdf(item.file, { requestId: item.requestId, paperId, signal: controller.signal, onProgress: (progress) => patch(item.id, { progress }) }).then((result) => {
      patch(item.id, { state: 'accepted', progress: 1, accepted: result })
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      void client.invalidateQueries({ queryKey: queryKeys.jobs.all })
      void client.invalidateQueries({ queryKey: queryKeys.fulltext(result.paper_id) })
      if (mounted.current) accepted.current?.(result, item.file)
    }, (error: unknown) => {
      if (error instanceof DOMException && error.name === 'AbortError') return
      patch(item.id, { state: 'failed', error: error instanceof Error ? error : new Error('The upload failed. Try again.') })
    }).finally(() => controllers.current.delete(item.id))
  }, [client, paperId, patch])

  const add = useCallback((files: File[]) => {
    const next = files.map((file): UploadItem => {
      const problem = validatePdf(file)
      return { id: crypto.randomUUID(), file, requestId: crypto.randomUUID(), state: problem ? 'failed' : 'uploading', progress: 0, error: problem ? new Error(problem) : undefined, invalid: !!problem }
    })
    setItems((list) => [...list, ...next])
    for (const item of next) if (item.state === 'uploading') send(item)
  }, [send])
  const retry = useCallback((item: UploadItem) => {
    if (item.invalid) return
    patch(item.id, { state: 'uploading', progress: 0, error: undefined })
    send(item)
  }, [patch, send])
  const remove = useCallback((id: string) => {
    controllers.current.get(id)?.abort()
    setItems((list) => list.filter((item) => item.id !== id))
  }, [])
  const clear = useCallback(() => setItems((list) => list.filter((item) => item.state === 'uploading')), [])
  return { items, add, retry, remove, clear }
}
