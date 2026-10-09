import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { UploadAccepted } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'
import { validatePdf } from './validate-pdf'

/** Uploads one PDF. Every attempt gets its own request UUID; the server deduplicates identical files. */
export function useUploadPdf(paperId?: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const problem = validatePdf(file)
      if (problem) throw new Error(problem)
      const body = new FormData()
      body.append('file', file)
      body.append('request_id', crypto.randomUUID())
      if (paperId) body.append('paper_id', paperId)
      return api<UploadAccepted>('/documents', { method: 'POST', body })
    },
    onSuccess: (accepted) => {
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
      void client.invalidateQueries({ queryKey: queryKeys.jobs.all })
      void client.invalidateQueries({ queryKey: queryKeys.papers.detail(accepted.paper_id) })
      void client.invalidateQueries({ queryKey: queryKeys.fulltext(accepted.paper_id) })
    },
  })
}
