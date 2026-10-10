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
// An estimate reads as one: two significant figures, so 52,964 tokens is "about 53,000".
function rounded(count: number) { return Number(count.toPrecision(2)) }
function roughly(count: number) { return rounded(count).toLocaleString() }
// OpenAI's rule of thumb for English text: a token is about three-quarters of a word. Words come from the rounded
// token count shown beside them, so the two figures agree.
function words(tokens: number) { return roughly(rounded(tokens) * 0.75) }
/** A search index choice by its catalog label (its trade-off), else by the model's own name. */
function choiceName(profile: EmbeddingProfile) { return profile.label ?? profile.display_name }
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
                  ? `Your library has no papers yet, so there is nothing to rebuild. New papers will be indexed with “${choiceName(profile)}”.`
                  : data
                    ? `Switching the search index to “${choiceName(profile)}” reads ${papers(data.papers)} in your library again in the background: about ${roughly(data.tokens)} tokens, roughly ${words(data.tokens)} words.`
                    : `Switching the search index to “${choiceName(profile)}” reads every paper in your library again in the background.`}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="grid gap-2 text-sm text-muted-foreground">
              {profile.label && <p className="text-xs">Model: {profile.display_name}</p>}
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
      description={<p>Meaning search: this model reads each paper to build the index that matches your question by meaning, not only by its words. Switching models reads every paper again in the background, and each paper keeps its current index until its new one is ready.</p>}
    >
      {placeholder}
      {profiles && saved && <ChoiceList label="Search index model">
        {withoutOpenModels(profiles, openModels, saved.embedding_profile).map((profile) => {
          // A saved local model stays visible while open models are off, but it cannot be chosen again.
          const frozen = !openModels && profile.provider === 'ollama'
          return (
            <ChoiceRow key={profile.key} name={id} value={profile.key} checked={chosen === profile.key} disabled={frozen} onSelect={() => { if (profile.key !== saved.embedding_profile) { setPending(profile); setConfirming(true) } }} title={choiceName(profile)}>
              {/* The model's own name is secondary: the choice leads with what it trades. */}
              {profile.label && <span className="text-xs">{profile.display_name}</span>}{' '}
              {profile.description && <span>{profile.description}</span>}{' '}
              {!frozen && <span>{profile.price_per_million > 0 ? `Indexing costs $${profile.price_per_million} per million tokens, about ${words(1_000_000)} words.` : 'Runs on this server, with no per-token cost.'}</span>}{' '}
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

/** Reordering by relevance (reranking) is on or off; with more than one model to choose from, a list says which. Saves at once. */
function Reordering({ rerankers, saved }: { rerankers: Reranker[]; saved: RetrievalSettings }) {
  const id = useId()
  const openModels = useOpenModels()
  const save = useSaveRetrievalSettings()
  const listed = withoutOpenModels(rerankers, openModels, saved.reranker)
  const usable = listed.find((reranker) => reranker.status === 'available')
  const current = save.isPending && save.variables ? save.variables.reranker : saved.reranker
  const active = listed.find((reranker) => reranker.key === current)
  const reads = (active ?? usable)?.candidates
  const choose = (reranker: string | null) => save.mutate({ embedding_profile: saved.embedding_profile, reranker })
  // What a reranker adds to each question comes from the catalog; a frozen local one says nothing while open models are off.
  const note = (reranker?: Reranker) => (reranker && (openModels || reranker.provider !== 'ollama') ? reranker.description : null)
  return (
    <SettingsSection
      headingId={id}
      title="Reordering by relevance"
      status={save.isSuccess ? 'Saved' : ''}
      description={(
        <>
          <p>{[
            `After search, a second model reads the ${reads ? `${reads} ` : ''}best matches and moves the passages that best answer your question to the top, so the answer cites stronger evidence.`,
            note(active ?? usable),
            'When off, the answer uses the passages in the order search found them, with no extra time or cost.',
          ].filter(Boolean).join(' ')}</p>
          {!listed.length && <p>This server offers no model for reordering.</p>}
        </>
      )}
      control={<Switch aria-labelledby={id} checked={current !== null} disabled={!usable && current === null} onCheckedChange={(on) => choose(on ? usable?.key ?? null : null)} className="mt-0.5" />}
    >
      {/* The model's name is secondary: the setting leads with what it does. */}
      {current !== null && listed.length === 1 && active?.status === 'available' && <p className="-mt-2 text-xs text-muted-foreground">Runs on {active.display_name}, separate from the model that answers.</p>}
      {current !== null && (listed.length > 1 || active?.status !== 'available') && (
        <ChoiceList label="Reordering model">
          {listed.map((reranker) => (
            <ChoiceRow key={reranker.key} name={id} value={reranker.key} checked={current === reranker.key} disabled={reranker.status !== 'available'} onSelect={() => choose(reranker.key)} title={reranker.display_name}>
              {note(reranker) && <span>{note(reranker)}</span>}{' '}
              {reranker.status !== 'available' && <UnavailableReason profile={reranker} />}
            </ChoiceRow>
          ))}
        </ChoiceList>
      )}
      <ErrorNotice error={save.error} />
    </SettingsSection>
  )
}

/** The library-wide search index model and reordering by relevance; both read the same saved retrieval settings. */
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
      {ready && <Reordering rerankers={ready.page.rerankers ?? []} saved={ready.saved} />}
    </>
  )
}
