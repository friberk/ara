import { useId } from 'react'
import { Link } from 'react-router-dom'
import type { EmbeddingProfile } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { useOpenModels, withoutOpenModels } from '@/hooks/queries/features'
import { cn } from '@/lib/utils'

const statusBadges: Record<EmbeddingProfile['status'], { label: string; tone: string }> = {
  available: { label: 'Available', tone: 'bg-success-muted text-success' },
  unavailable: { label: 'Unavailable', tone: 'bg-muted text-muted-foreground' },
}

/** One row of a model radio list. A disabled row keeps its details, such as how to install the model, readable. */
export function OptionRow({ name, value, checked, onSelect, title, badge, disabled, children }: { name: string; value: string; checked: boolean; onSelect: () => void; title: string; badge?: React.ReactNode; disabled?: boolean; children: React.ReactNode }) {
  const id = useId()
  return (
    <label htmlFor={`${id}-radio`} className={cn('flex gap-3 px-4 py-3.5 transition-colors', disabled ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-muted/50', checked && 'bg-muted/60 hover:bg-muted/60')}>
      <input id={`${id}-radio`} type="radio" name={name} value={value} checked={checked} disabled={disabled} onChange={onSelect} aria-labelledby={`${id}-name`} aria-describedby={`${id}-details`} className="mt-0.5 size-4 shrink-0 accent-foreground disabled:cursor-not-allowed disabled:opacity-50" />
      <span className="grid min-w-0 flex-1 gap-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span id={`${id}-name`} className="text-sm font-medium">{title}</span>
          {badge}
        </span>
        <span id={`${id}-details`} className="grid gap-0.5 text-xs text-muted-foreground">{children}</span>
      </span>
    </label>
  )
}

/** Whether a listed model can be used now. */
export function StatusBadge({ status }: { status: EmbeddingProfile['status'] }) {
  const badge = statusBadges[status]
  return <Badge variant="secondary" className={cn('font-normal', badge.tone)}>{badge.label}</Badge>
}

/** A local model's reason and a way to install it; shared by the Settings lists and a paper's index panel. */
export function UnavailableReason({ profile }: { profile: Pick<EmbeddingProfile, 'unavailable_reason' | 'local_model_key'> }) {
  const openModels = useOpenModels()
  return (
    <span className="flex flex-wrap gap-x-2">
      <span>{profile.unavailable_reason ?? 'Not available on the server right now.'}</span>{' '}
      {profile.local_model_key && openModels && <Link to="/settings#local-models" className="text-foreground underline decoration-foreground/25 hover:decoration-foreground">Go to Local models</Link>}
    </span>
  )
}

/** What a search model costs: hosted models by the million tokens, local models nothing. */
function priceLabel(profile: Pick<EmbeddingProfile, 'provider' | 'price_per_million'>) {
  return profile.price_per_million > 0 ? `$${profile.price_per_million} per million tokens` : profile.provider === 'ollama' ? 'Runs locally. No per-token cost.' : null
}

/** Radio list of the search models the whole library can use, in the style of the default-model list. */
export function ProfileOptions({ profiles, value, onChange, label }: { profiles: EmbeddingProfile[]; value: string; onChange: (key: string) => void; label: string }) {
  const name = useId()
  const openModels = useOpenModels()
  return (
    <div role="radiogroup" aria-label={label} className="divide-y overflow-hidden rounded-xl border">
      {withoutOpenModels(profiles, openModels, value).map((profile) => {
        // A saved local model stays visible while open models are off, but it cannot be chosen again.
        const frozen = !openModels && profile.provider === 'ollama'
        return (
          <OptionRow key={profile.key} name={name} value={profile.key} checked={value === profile.key} onSelect={() => onChange(profile.key)} title={profile.display_name} badge={<StatusBadge status={profile.status} />} disabled={frozen}>
            <span className="font-mono break-all">{profile.model_id}</span>
            {!frozen && priceLabel(profile) && <span>{priceLabel(profile)}</span>}
            {/* Still selectable: the server accepts it and papers keep their current index until the model is ready. */}
            {profile.status === 'unavailable' && <UnavailableReason profile={profile} />}
          </OptionRow>
        )
      })}
    </div>
  )
}
