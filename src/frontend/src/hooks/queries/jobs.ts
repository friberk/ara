import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json, query } from '@/api/client'
import type { Collection, JobView } from '@/api/types'
import { queryKeys } from '@/lib/query-keys'

export type JobFilters = { paperId?: string | null; kind?: string | null; active?: boolean | null }
const settled = (state: string | undefined) => state === 'completed' || state === 'failed'

export function useJobs(filters: JobFilters = {}, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.jobs.list(filters),
    queryFn: ({ signal }) => api<Collection<JobView>>(`/jobs${query({ paper_id: filters.paperId, kind: filters.kind, active: filters.active ?? undefined })}`, { signal }),
    refetchInterval: (current) => current.state.data?.items.some((job) => !settled(job.state)) ? 2000 : false,
    enabled: options.enabled ?? true,
  })
}

export function useJob(jobId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(jobId ?? ''),
    queryFn: ({ signal }) => api<JobView>(`/jobs/${jobId}`, { signal }),
    enabled: !!jobId,
    refetchInterval: (current) => settled(current.state.data?.state) ? false : 1500,
  })
}

export function useRetryJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api<JobView>(`/jobs/${jobId}/retry`, json('POST', {})),
    onSuccess: () => { void client.invalidateQueries({ queryKey: queryKeys.jobs.all }); void client.invalidateQueries({ queryKey: queryKeys.papers.all }) },
  })
}
