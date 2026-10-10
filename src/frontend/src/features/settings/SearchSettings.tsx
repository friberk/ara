import { useId, useState } from 'react'
import type { EmbeddingProfile, Reranker, ReindexEstimate, RetrievalSettings } from '@/api/types'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { UnavailableReason } from '@/components/retrieval/UnavailableReason'
import { useOpenModels, withoutOpenModels } from '@/hooks/queries/features'
import { useEmbeddingProfiles, useReindexEstimate, useRetrievalSettings, useSaveRetrievalSettings } from '@/hooks/queries/retrieval'
import { ChoiceList, ChoiceRow, SettingsSection } from './parts'

function papers(count: number) { return count === 1 ? 'the one paper' : `all ${count.toLocaleString()} papers` }
function cost(estimate: ReindexEstimate) {
  if (estimate.price_per_million === 0) return 'none, because this model runs on this server'
  return estimate.estimated_cost_usd < 0.01 ? 'less than $0.01' : `$${estimate.estimated_cost_usd.toFixed(2)}`
}

/** Switching the library's search index model rebuilds every paper's index, so it asks first and says how much work and money that is. */
function RebuildDialog({ profile, open, onCancel, onConfirm }: { profile: EmbeddingProfile | null; open: boolean; onCancel: () => void; onConfirm: () => void }) {
  const estimate = useReindexEstimate(open && profile ? profile.key : null)
  const data = estimate.data
  const empty = data?.papers === 0
  return (
    <AlertDialog open={open} onOpenChange={(next) => { if (!next) onCancel() }}>
      <AlertDialogContent>
        {profile && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{empty ? 'Switch the search index model?' : 'Rebuild the search index?'}</AlertDialogTitle>
              <AlertDialogDescription>
                {empty
                  ? `Your library has no papers yet, so there is nothing to rebuild. New papers will be indexed with ${profile.display_name}.`
                  : data
                    ? `Switching to ${profile.display_name} rebuilds the index for ${papers(data.papers)} in your library, about ${data.tokens.toLocaleString()} tokens, in the background.`
                    : `Switching to ${profile.display_name} rebuilds the index for every paper in your library, in the background.`}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="grid gap-2 text-sm text-muted-foreground">
              {estimate.isPending && <p role="status">Counting your papers…</p>}
              {data && !empty && <p>Estimated cost: {cost(data)}.</p>}
              {data && !empty && <p>Questions keep working while it runs: each paper keeps its current index until its new one is ready.</p>}
              {profile.status === 'unavailable' && <p>{profile.unavailable_reason ?? 'This model is not available right now.'} Papers keep their current index until it is.</p>}
              <ErrorNotice error={estimate.error} retry={() => { void estimate.refetch() }} />
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction disabled={!data} onClick={onConfirm}>{empty ? 'Switch model' : 'Rebuild index'}</AlertDialogAction>
            </AlertDialogFooter>
          </>
        )}
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** The library's search index model. Until settings load, `placeholder` (loading, an error or an empty list) stands in for the choices. */
function SearchIndex({ profiles, saved, placeholder }: { profiles?: EmbeddingProfile[]; saved?: RetrievalSettings; placeholder?: React.ReactNode }) {
  const id = useId()
  const openModels = useOpenModels()
  const save = useSaveRetrievalSettings()
  // The model being confirmed stays set while the dialog closes, so its text does not vanish mid-animation.
  const [pending, setPending] = useState<EmbeddingProfile | null>(null)
  const [confirming, setConfirming] = useState(false)
  const chosen = confirming && pending ? pending.key : save.isPending && save.variables ? save.variables.embedding_profile : saved?.embedding_profile
  return (
    <SettingsSection
      headingId={id}
      title="Search index"
      status={save.isSuccess ? 'Rebuilding in the background' : ''}
      description={<p>Search finds the passages in your papers that answer a question by their meaning, not only their words. This model builds that index for the whole library, so switching rebuilds the index for every paper in the background.</p>}
    >
      {placeholder}
      {profiles && saved && <ChoiceList label="Search index model">
        {withoutOpenModels(profiles, openModels, saved.embedding_profile).map((profile) => {
          // A saved local model stays visible while open models are off, but it cannot be chosen again.
          const frozen = !openModels && profile.provider === 'ollama'
          return (
            <ChoiceRow key={profile.key} name={id} value={profile.key} checked={chosen === profile.key} disabled={frozen} onSelect={() => { if (profile.key !== saved.embedding_profile) { setPending(profile); setConfirming(true) } }} title={profile.display_name}>
              {!frozen && <span>{profile.price_per_million > 0 ? `Indexing costs $${profile.price_per_million} per million tokens.` : 'Runs on this server, with no per-token cost.'}</span>}{' '}
              {/* Still selectable: the server accepts it and papers keep their current index until the model is ready. */}
              {profile.status === 'unavailable' && <UnavailableReason profile={profile} />}
            </ChoiceRow>
          )
        })}
      </ChoiceList>}
      <ErrorNotice error={save.error} />
      <RebuildDialog profile={pending} open={confirming} onCancel={() => setConfirming(false)} onConfirm={() => { if (pending && saved) save.mutate({ ...saved, embedding_profile: pending.key }); setConfirming(false) }} />
    </SettingsSection>
  )
}

// What each kind of reranker costs, by provider; the models themselves come from the server's catalog.
const tradeoffs: Record<Reranker['provider'], string> = {
  openai: 'Fast, with a small cost per question.',
  ollama: 'Private. Adds about 10 seconds to each question.',
}

/** Reranking is on or off; with more than one reranker to choose from, a list says which one. Saves at once. */
function Reranking({ rerankers, saved }: { rerankers: Reranker[]; saved: RetrievalSettings }) {
  const id = useId()
  const openModels = useOpenModels()
  const save = useSaveRetrievalSettings()
  const listed = withoutOpenModels(rerankers, openModels, saved.reranker)
  const usable = listed.find((reranker) => reranker.status === 'available')
  const current = save.isPending && save.variables ? save.variables.reranker : saved.reranker
  const active = listed.find((reranker) => reranker.key === current)
  const reads = (active ?? usable)?.candidates
  const choose = (reranker: string | null) => save.mutate({ embedding_profile: saved.embedding_profile, reranker })
  return (
    <SettingsSection
      headingId={id}
      title="Reranking"
      status={save.isSuccess ? 'Saved' : ''}
      description={(
        <>
          <p>After search, a second model reads the {reads ? `${reads} ` : ''}best matches and puts the passages that answer your question first. Answers cite better evidence, but each question takes a few seconds longer and costs a little more.</p>
          {!listed.length && <p>This server offers no reranking model.</p>}
          {current !== null && listed.length === 1 && active?.status === 'available' && <p>Uses {active.display_name}.</p>}
        </>
      )}
      control={<Switch aria-labelledby={id} checked={current !== null} disabled={!usable && current === null} onCheckedChange={(on) => choose(on ? usable?.key ?? null : null)} className="mt-0.5" />}
    >
      {current !== null && (listed.length > 1 || active?.status !== 'available') && (
        <ChoiceList label="Reranking model">
          {listed.map((reranker) => (
            <ChoiceRow key={reranker.key} name={id} value={reranker.key} checked={current === reranker.key} disabled={reranker.status !== 'available'} onSelect={() => choose(reranker.key)} title={reranker.display_name}>
              {(openModels || reranker.provider !== 'ollama') && <span>{tradeoffs[reranker.provider]}</span>}{' '}
              {reranker.status !== 'available' && <UnavailableReason profile={reranker} />}
            </ChoiceRow>
          ))}
        </ChoiceList>
      )}
      <ErrorNotice error={save.error} />
    </SettingsSection>
  )
}

/** The library-wide search index model and reranking; both read the same saved retrieval settings. */
export function SearchSettings() {
  const profiles = useEmbeddingProfiles()
  const saved = useRetrievalSettings()
  const error = profiles.error ?? saved.error
  const ready = !error && profiles.data?.items.length && saved.data ? { page: profiles.data, saved: saved.data } : null
  // One Search index section throughout, so loading turns into the choices in place.
  const placeholder = error ? <ErrorNotice error={error} retry={() => { void profiles.refetch(); void saved.refetch() }} />
    : !profiles.data || !saved.data ? <div role="status" className="grid gap-3"><span className="sr-only">Loading search settings…</span><Skeleton className="h-20 w-full rounded-xl" /><Skeleton className="h-20 w-full rounded-xl" /></div>
      : !ready ? <EmptyState title="No search index models">The server lists none. Check its configuration, then reopen Settings.</EmptyState> : null
  return (
    <>
      <SearchIndex profiles={ready?.page.items} saved={ready?.saved} placeholder={placeholder} />
      {ready && <Reranking rerankers={ready.page.rerankers ?? []} saved={ready.saved} />}
    </>
  )
}
