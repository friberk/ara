import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '@/api/client'
import type { DocumentState, Job, MetadataSettings, MetadataSource } from '@/api/types'
import { isActiveJob } from '@/components/jobs/job-labels'
import { queryKeys } from '@/lib/query-keys'
import { useJobs } from './jobs'

// Kept beside its hooks rather than in the shared key map (ARA-086).
const settingsKey = ['metadata', 'settings'] as const

/** Which catalog uploaded PDFs are looked up in first. Anything unexpected reads as the default, OpenAlex. */
export function useMetadataSettings() {
  return useQuery({
    queryKey: settingsKey,
    queryFn: async ({ signal }): Promise<MetadataSettings> => {
      const data = await api<Partial<MetadataSettings>>('/metadata/settings', { signal })
      return { source: data.source === 'semantic_scholar' ? 'semantic_scholar' : 'openalex' }
    },
  })
}

export function useSaveMetadataSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (source: MetadataSource) => api<MetadataSettings>('/metadata/settings', json('PUT', { source } satisfies MetadataSettings)),
    onSuccess: (data) => client.setQueryData(settingsKey, data),
  })
}

/**
 * The paper's latest catalog lookup. It is queued in the same commit that makes the PDF readable, so the list is read
 * again when the paper turns ready; when a lookup that was running settles, the paper and library refresh so an
 * improved title appears without a reload.
 */
export function usePaperLookup(paper: { id: string; document_status: DocumentState }): Job | null {
  const client = useQueryClient()
  const jobs = useJobs({ paperId: paper.id, kind: 'metadata' }, { enabled: paper.document_status !== 'metadata_only' })
  const lookup = jobs.data?.items.find((job) => job.kind === 'metadata' && job.paper_id === paper.id) ?? null
  const { refetch } = jobs
  const ready = paper.document_status === 'ready'
  const wasReady = useRef(ready)
  useEffect(() => {
    if (ready && !wasReady.current) void refetch()
    wasReady.current = ready
  }, [ready, refetch])
  const followed = useRef<string | null>(null)
  useEffect(() => {
    if (!lookup) return
    if (isActiveJob(lookup)) followed.current = lookup.id
    else if (followed.current === lookup.id) {
      followed.current = null
      void client.invalidateQueries({ queryKey: queryKeys.papers.all })
    }
  }, [lookup, client])
  return lookup
}
