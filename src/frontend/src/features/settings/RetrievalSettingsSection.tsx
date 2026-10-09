import { useId, useState } from 'react'
import type { EmbeddingProfile, Reranker, RetrievalSettings } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { ProfileOptions, UnavailableReason } from '@/components/retrieval/ProfileOptions'
import { useEmbeddingProfiles, useRetrievalSettings, useSaveRetrievalSettings } from '@/hooks/queries/retrieval'

/**
 * Opt-in reranking (ARA-074). It can only be turned on once the reranker model is installed; until then the saved
 * choice is kept and the reason says how to install it.
 */
function RerankSwitch({ reranker, checked, onCheckedChange }: { reranker: Reranker | null | undefined; checked: boolean; onCheckedChange: (checked: boolean) => void }) {
  const id = useId()
  const available = reranker?.status === 'available'
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border px-4 py-3.5">
      <div className="grid gap-1">
        <Label htmlFor={id}>Rerank results</Label>
        <div id={`${id}-details`} className="grid gap-0.5 text-xs text-muted-foreground">
          <p>Finds the most relevant passages more precisely. Adds about 10 seconds to each answer.</p>
          {!available && <UnavailableReason profile={reranker ?? { unavailable_reason: null, local_model_key: null }} />}
        </div>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={!available} aria-describedby={`${id}-details`} className="mt-0.5" />
    </div>
  )
}

function SearchSettingsForm({ profiles, reranker, saved }: { profiles: EmbeddingProfile[]; reranker: Reranker | null | undefined; saved: RetrievalSettings }) {
  const save = useSaveRetrievalSettings()
  const [choice, setChoice] = useState<Partial<RetrievalSettings>>({})
  const draft = { ...saved, ...choice }
  const dirty = draft.embedding_profile !== saved.embedding_profile || draft.reranker_enabled !== saved.reranker_enabled
  const change = (value: Partial<RetrievalSettings>) => { save.reset(); setChoice((previous) => ({ ...previous, ...value })) }
  return (
    <form className="grid gap-6" onSubmit={(event) => { event.preventDefault(); if (dirty) save.mutate(draft) }}>
      <ProfileOptions profiles={profiles} value={draft.embedding_profile} onChange={(key) => { if (key) change({ embedding_profile: key }) }} label="Default search model" />
      <RerankSwitch reranker={reranker} checked={draft.reranker_enabled} onCheckedChange={(enabled) => change({ reranker_enabled: enabled })} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" disabled={!dirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save search settings'}</Button>
        <p role="status" className="text-sm text-muted-foreground">{save.isSuccess && !dirty ? 'Search settings saved.' : ''}</p>
      </div>
      <ErrorNotice error={save.error} />
    </form>
  )
}

/** The default search model and opt-in reranking, saved together. */
export function RetrievalSettingsSection() {
  const profiles = useEmbeddingProfiles()
  const saved = useRetrievalSettings()
  const headingId = useId()
  const error = profiles.error ?? saved.error
  return (
    <section aria-labelledby={headingId} className="grid gap-6">
      <div className="grid gap-1">
        <h2 id={headingId} className="text-base font-semibold tracking-tight">Search and retrieval</h2>
        <p className="text-sm text-pretty text-muted-foreground">The search model finds the passages in a paper that answer your question. Papers use this default unless you change it in a paper’s Details.</p>
      </div>
      {(profiles.isPending || saved.isPending) && !error && (
        <div role="status" className="grid gap-3"><span className="sr-only">Loading search models…</span><Skeleton className="h-16 w-full rounded-xl" /><Skeleton className="h-16 w-full rounded-xl" /></div>
      )}
      <ErrorNotice error={error} retry={() => { void profiles.refetch(); void saved.refetch() }} />
      {profiles.data && saved.data && (profiles.data.items.length ? (
        <SearchSettingsForm profiles={profiles.data.items} reranker={profiles.data.reranker} saved={saved.data} />
      ) : (
        <EmptyState title="No search models configured">Configure search models on the server, then reload this page.</EmptyState>
      ))}
    </section>
  )
}
