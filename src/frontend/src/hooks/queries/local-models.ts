import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { Job } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

type ModelAction = { kind: 'download'; modelKey: string } | { kind: 'delete'; modelKey: string } | { kind: 'pause' | 'resume' | 'retry'; jobId: string }

/** Mutations only enqueue durable server operations; browser lifetime never owns a transfer. */
export function useModelAction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (action: ModelAction) => {
      const requestId = crypto.randomUUID()
      if (action.kind === 'download') return api<Job>(`/models/${encodeURIComponent(action.modelKey)}/download`, json('POST', { request_id: requestId }))
      if (action.kind === 'delete') return api<Job>(`/models/${encodeURIComponent(action.modelKey)}/installation`, { method: 'DELETE', headers: { 'Idempotency-Key': requestId } })
      return api<Job>(`/jobs/${encodeURIComponent(action.jobId)}/${action.kind}`, json('POST', { request_id: requestId }))
    },
    onSettled: () => {
      // Refresh conflicts too: another tab or a worker may have changed readiness.
      void client.invalidateQueries({ queryKey: queryKeys.models })
      void client.invalidateQueries({ queryKey: queryKeys.jobs.all })
    },
  })
}
