import { useId, useState } from 'react'
import { ChevronDown, CircleAlert, CircleCheck, CircleDashed, CircleSlash, LoaderCircle, type LucideIcon } from 'lucide-react'
import type { PaperRetrieval, RetrievalIndex } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { UnavailableReason } from '@/components/retrieval/ProfileOptions'
import { isBuilding, useEmbeddingProfiles, usePaperRetrieval, useRebuildPaperRetrieval } from '@/hooks/queries/retrieval'
import { cn } from '@/lib/utils'

type IndexView = 'ready' | 'building' | 'failed' | 'unavailable' | 'missing'
const badges: Record<IndexView, { label: string; tone: string; icon: LucideIcon }> = {
  ready: { label: 'Ready', tone: 'bg-success-muted text-success', icon: CircleCheck },
  building: { label: 'Building', tone: 'bg-warning-muted text-warning', icon: LoaderCircle },
  failed: { label: 'Failed', tone: 'bg-destructive/10 text-destructive', icon: CircleAlert },
  unavailable: { label: 'Unavailable', tone: 'bg-muted text-muted-foreground', icon: CircleSlash },
  missing: { label: 'Not built yet', tone: 'bg-muted text-muted-foreground', icon: CircleDashed },
}

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
  const badge = badges[view]
  const percent = index && view === 'building' && index.total > 0 ? Math.min(99, Math.round(100 * index.embedded / index.total)) : null
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="grid min-w-0 gap-1">
          <p className="text-sm">Searching with <span className="font-medium">{profile?.display_name ?? data.effective_profile}</span></p>
          {profile && <p className="font-mono text-xs break-all text-muted-foreground">{profile.model_id}</p>}
        </div>
        <Badge variant="secondary" className={cn('font-normal', badge.tone)}><badge.icon data-icon="inline-start" aria-hidden="true" className={view === 'building' ? 'motion-safe:animate-spin' : undefined} />{badge.label}</Badge>
      </div>
      {view === 'building' && (
        <div className="grid gap-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted-foreground">
            <span className="tabular">{index && index.total > 0 ? `${index.embedded.toLocaleString()} of ${count(index.total, 'passage')}` : 'Waiting to start'}</span>
            {percent !== null && <span className="tabular">{percent}%</span>}
          </div>
          <Progress value={percent} aria-label="Search index progress" />
        </div>
      )}
      <p className="text-sm text-muted-foreground tabular">{count(data.chunk_count, 'passage')} · {count(data.section_count, 'section')}</p>
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

/**
 * The ⓘ sheet's Advanced disclosure (ARA-097), collapsed by default: the library model's index for this paper, with
 * Rebuild. It loads only when opened.
 */
export function SearchIndexPanel({ paperId }: { paperId: string }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="grid gap-3">
      <h3 className="text-sm font-medium">
        <CollapsibleTrigger className="group flex w-full items-center justify-between gap-3 rounded-md text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
          Advanced
          <ChevronDown aria-hidden="true" className="size-4 text-muted-foreground motion-safe:transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
      </h3>
      <CollapsibleContent>
        <section aria-labelledby={`${id}-index`} className="grid gap-3">
          <h4 id={`${id}-index`} className="text-sm font-medium">Search index</h4>
          <IndexDetails paperId={paperId} />
        </section>
      </CollapsibleContent>
    </Collapsible>
  )
}
