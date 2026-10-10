import { useId } from 'react'
import { LoaderCircle } from 'lucide-react'
import type { PaperRetrieval, RetrievalIndex } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { UnavailableReason } from '@/components/retrieval/UnavailableReason'
import { isBuilding, useEmbeddingProfiles, usePaperRetrieval, useRebuildPaperRetrieval } from '@/hooks/queries/retrieval'

type IndexView = 'ready' | 'building' | 'failed' | 'unavailable' | 'missing'

/** The index for the library model: one still building wins, else the most recently updated. */
function currentIndex(data: PaperRetrieval): RetrievalIndex | undefined {
  const own = data.indexes.filter((index) => index.profile === data.effective_profile)
  return own.find(isBuilding) ?? own.reduce<RetrievalIndex | undefined>((latest, index) => !latest || (index.updated_at ?? '') > (latest.updated_at ?? '') ? index : latest, undefined)
}
function viewOf(index: RetrievalIndex | undefined): IndexView {
  if (!index) return 'missing'
  return index.state === 'queued' || index.state === 'embedding' ? 'building' : index.state
}
function count(value: number, noun: string) { return `${value.toLocaleString()} ${noun}${value === 1 ? '' : 's'}` }

function IndexDetails({ paperId }: { paperId: string }) {
  const retrieval = usePaperRetrieval(paperId)
  const profiles = useEmbeddingProfiles()
  const rebuild = useRebuildPaperRetrieval(paperId)
  const error = retrieval.error ?? profiles.error
  if (error) return <ErrorNotice error={error} retry={() => { void retrieval.refetch(); void profiles.refetch() }} />
  if (!retrieval.data || !profiles.data) return <div role="status" className="grid gap-2"><span className="sr-only">Loading search index…</span><Skeleton className="h-5 w-2/3" /><Skeleton className="h-4 w-1/3" /></div>
  const data = retrieval.data
  const items = profiles.data.items
  const profile = items.find((item) => item.key === data.effective_profile)
  const index = currentIndex(data)
  const view = viewOf(index)
  const percent = index && view === 'building' && index.total > 0 ? Math.min(99, Math.round(100 * index.embedded / index.total)) : null
  return (
    <div className="grid gap-4">
      {/* One plain sentence, the model named once (ARA-101 follow-up). A ready index says nothing more. The name never
          breaks at its own hyphens ("text-embedding-" / "3-large"); the line breaks before it instead. */}
      <p className="text-sm text-pretty tabular">
        {`Searching ${count(data.chunk_count, 'passage')} in ${count(data.section_count, 'section')} with `}
        <span className="whitespace-nowrap">{profile?.display_name ?? data.effective_profile}</span>.
      </p>
      {view === 'building' && (
        <div className="grid gap-2">
          <p className="flex items-center gap-2 text-sm"><LoaderCircle aria-hidden="true" className="size-3.5 text-muted-foreground motion-safe:animate-spin" />Building the index</p>
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted-foreground">
            <span className="tabular">{index && index.total > 0 ? `${index.embedded.toLocaleString()} of ${count(index.total, 'passage')}` : 'Waiting to start'}</span>
            {percent !== null && <span className="tabular">{percent}%</span>}
          </div>
          <Progress value={percent} aria-label="Search index progress" />
        </div>
      )}
      {view === 'building' && <p className="text-sm text-muted-foreground">{data.mode === 'hybrid' ? 'Answers keep using the previous index until the new one is ready.' : 'Answers use keyword search until the index is ready.'}</p>}
      {view === 'missing' && <p className="text-sm text-muted-foreground">{data.mode_note ?? 'Answers use keyword search until the index is built.'}</p>}
      {view === 'unavailable' && <div className="text-sm text-muted-foreground">{index?.error?.message ?? (profile?.status === 'unavailable' ? <UnavailableReason profile={profile} /> : data.mode_note ?? 'This search model is not available right now.')}</div>}
      {view === 'failed' && <p role="alert" className="text-sm text-destructive">{index?.error?.message ?? 'The search index could not be built. Rebuild to try again.'}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={view === 'building' || rebuild.isPending} onClick={() => rebuild.mutate()}>{view === 'missing' ? 'Build index' : 'Rebuild index'}</Button>
      </div>
      <ErrorNotice error={rebuild.error} />
    </div>
  )
}

/** The library model's index for this paper, in the ⓘ dialog (ARA-101): it loads when the dialog opens. */
export function SearchIndexPanel({ paperId }: { paperId: string }) {
  const id = useId()
  return (
    <section aria-labelledby={`${id}-index`} className="grid gap-3">
      <h3 id={`${id}-index`} className="text-sm font-medium">Search index</h3>
      <IndexDetails paperId={paperId} />
    </section>
  )
}
