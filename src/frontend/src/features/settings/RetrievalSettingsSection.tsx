import { useId, useState } from 'react'
import type { EmbeddingProfile, Reranker, ReindexEstimate, RetrievalSettings } from '@/api/types'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { ProfileOptions } from '@/components/retrieval/ProfileOptions'
import { RerankerOptions } from '@/components/retrieval/RerankerOptions'
import { useEmbeddingProfiles, useReindexEstimate, useRetrievalSettings, useSaveRetrievalSettings } from '@/hooks/queries/retrieval'

function count(value: number, noun: string) { return `${value.toLocaleString()} ${noun}${value === 1 ? '' : 's'}` }
function cost(estimate: ReindexEstimate) {
  if (estimate.price_per_million === 0) return 'none, this model runs locally'
  return estimate.estimated_cost_usd < 0.01 ? 'less than $0.01' : `$${estimate.estimated_cost_usd.toFixed(2)}`
}

/** Switching the library model re-embeds every paper, so it asks first and says how much work and money that is. */
function ReembedDialog({ profile, open, onOpenChange, onConfirm }: { profile: EmbeddingProfile; open: boolean; onOpenChange: (open: boolean) => void; onConfirm: () => void }) {
  const estimate = useReindexEstimate(open ? profile.key : null)
  const data = estimate.data
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Re-embed the whole library?</AlertDialogTitle>
          <AlertDialogDescription>
            {data ? (data.papers > 0 ? `Switching to ${profile.display_name} re-embeds your whole library in the background: ${count(data.papers, 'paper')}, about ${data.tokens.toLocaleString()} tokens.` : `You have no papers to re-embed yet. ${profile.display_name} will index the papers you add.`) : `Switching to ${profile.display_name} re-embeds your whole library in the background.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="grid gap-2 text-sm text-muted-foreground">
          {estimate.isPending && <p role="status">Counting your papers…</p>}
          {data && data.papers > 0 && <p>Estimated cost: {cost(data)}.</p>}
          {data && data.papers > 0 && <p>Questions keep working meanwhile: each paper uses its current search index until the new one is ready.</p>}
          {profile.status === 'unavailable' && <p>{profile.unavailable_reason ?? 'This model is not available right now.'} Papers keep their current index until it is.</p>}
          <ErrorNotice error={estimate.error} retry={() => { void estimate.refetch() }} />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction disabled={!data} onClick={onConfirm}>Re-embed library</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function SearchSettingsForm({ profiles, rerankers, saved }: { profiles: EmbeddingProfile[]; rerankers: Reranker[]; saved: RetrievalSettings }) {
  const save = useSaveRetrievalSettings()
  const [choice, setChoice] = useState<Partial<RetrievalSettings>>({})
  const [confirming, setConfirming] = useState(false)
  const draft = { ...saved, ...choice }
  const switching = draft.embedding_profile !== saved.embedding_profile
  const dirty = switching || draft.reranker !== saved.reranker
  const chosen = profiles.find((profile) => profile.key === draft.embedding_profile)
  const change = (value: Partial<RetrievalSettings>) => { save.reset(); setChoice((previous) => ({ ...previous, ...value })) }
  return (
    <form className="grid gap-6" onSubmit={(event) => { event.preventDefault(); if (switching) setConfirming(true); else if (dirty) save.mutate(draft) }}>
      <ProfileOptions profiles={profiles} value={draft.embedding_profile} onChange={(key) => change({ embedding_profile: key })} label="Search model" />
      <RerankerOptions rerankers={rerankers} value={draft.reranker} onChange={(key) => change({ reranker: key })} label="Rerank results" />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" disabled={!dirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save search settings'}</Button>
        <p role="status" className="text-sm text-muted-foreground">{save.isSuccess && !dirty ? 'Search settings saved.' : ''}</p>
      </div>
      <ErrorNotice error={save.error} />
      {chosen && <ReembedDialog profile={chosen} open={confirming} onOpenChange={setConfirming} onConfirm={() => save.mutate(draft)} />}
    </form>
  )
}

/** The library-wide search model and how results are reranked, saved together. */
export function RetrievalSettingsSection() {
  const profiles = useEmbeddingProfiles()
  const saved = useRetrievalSettings()
  const headingId = useId()
  const error = profiles.error ?? saved.error
  return (
    <section aria-labelledby={headingId} className="grid gap-6">
      <div className="grid gap-1">
        <h2 id={headingId} className="text-base font-semibold tracking-tight">Search and retrieval</h2>
        <p className="text-sm text-pretty text-muted-foreground">The search model finds the passages in a paper that answer your question. One model searches the whole library, so changing it re-embeds every paper in the background.</p>
      </div>
      {(profiles.isPending || saved.isPending) && !error && (
        <div role="status" className="grid gap-3"><span className="sr-only">Loading search models…</span><Skeleton className="h-16 w-full rounded-xl" /><Skeleton className="h-16 w-full rounded-xl" /></div>
      )}
      <ErrorNotice error={error} retry={() => { void profiles.refetch(); void saved.refetch() }} />
      {profiles.data && saved.data && (profiles.data.items.length ? (
        <SearchSettingsForm profiles={profiles.data.items} rerankers={profiles.data.rerankers ?? []} saved={saved.data} />
      ) : (
        <EmptyState title="No search models configured">Configure search models on the server, then reload this page.</EmptyState>
      ))}
    </section>
  )
}
