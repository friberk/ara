import { useId, useState } from 'react'
import type { EmbeddingProfile, RetrievalSettings } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { ProfileOptions } from '@/components/retrieval/ProfileOptions'
import { useEmbeddingProfiles, useRetrievalSettings, useSaveRetrievalSettings } from '@/hooks/queries/retrieval'

function SearchModelForm({ profiles, saved }: { profiles: EmbeddingProfile[]; saved: RetrievalSettings }) {
  const save = useSaveRetrievalSettings()
  const [choice, setChoice] = useState<string | null>(null)
  const draft = choice ?? saved.embedding_profile
  const dirty = draft !== saved.embedding_profile
  return (
    <form className="grid gap-6" onSubmit={(event) => { event.preventDefault(); if (dirty) save.mutate({ ...saved, embedding_profile: draft }) }}>
      <ProfileOptions profiles={profiles} value={draft} onChange={(key) => { save.reset(); setChoice(key) }} label="Default search model" />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" disabled={!dirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save search model'}</Button>
        <p role="status" className="text-sm text-muted-foreground">{save.isSuccess && !dirty ? 'Search model saved.' : ''}</p>
      </div>
      <ErrorNotice error={save.error} />
    </form>
  )
}

/** The default search model. Saving keeps every other retrieval setting as the server holds it. */
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
        <SearchModelForm profiles={profiles.data.items} saved={saved.data} />
      ) : (
        <EmptyState title="No search models configured">Configure search models on the server, then reload this page.</EmptyState>
      ))}
    </section>
  )
}
