import { useId } from 'react'
import { Link } from 'react-router-dom'
import type { EmbeddingProfile } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const statusBadges: Record<EmbeddingProfile['status'], { label: string; tone: string }> = {
  available: { label: 'Available', tone: 'bg-success-muted text-success' },
  unavailable: { label: 'Unavailable', tone: 'bg-muted text-muted-foreground' },
}

function ProfileOption({ profile, name, checked, onSelect }: { profile: EmbeddingProfile; name: string; checked: boolean; onSelect: () => void }) {
  const id = useId()
  const badge = statusBadges[profile.status]
  return (
    <label htmlFor={`${id}-radio`} className={cn('flex cursor-pointer gap-3 px-4 py-3.5 transition-colors hover:bg-muted/50', checked && 'bg-muted/60 hover:bg-muted/60')}>
      <input id={`${id}-radio`} type="radio" name={name} value={profile.key} checked={checked} onChange={onSelect} aria-labelledby={`${id}-name`} aria-describedby={`${id}-details`} className="mt-0.5 size-4 shrink-0 accent-foreground" />
      <span className="grid min-w-0 flex-1 gap-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span id={`${id}-name`} className="text-sm font-medium">{profile.display_name}</span>
          <Badge variant="secondary" className={cn('font-normal', badge.tone)}>{badge.label}</Badge>
        </span>
        <span id={`${id}-details`} className="grid gap-0.5 text-xs text-muted-foreground">
          <span className="font-mono break-all">{profile.model_id}</span>
          {/* Still selectable: the server accepts it and the paper searches by keyword until the model is ready. */}
          {profile.status === 'unavailable' && (
            <span className="flex flex-wrap gap-x-2">
              <span>{profile.unavailable_reason ?? 'Not available on the server right now.'}</span>
              {profile.local_model_key && <Link to="/settings#local-models" className="text-foreground underline decoration-foreground/25 hover:decoration-foreground">Go to Local models</Link>}
            </span>
          )}
        </span>
      </span>
    </label>
  )
}

/** Radio list of search models in the style of the default-model list. */
export function ProfileOptions({ profiles, value, onChange, label }: { profiles: EmbeddingProfile[]; value: string; onChange: (key: string) => void; label: string }) {
  const name = useId()
  return (
    <div role="radiogroup" aria-label={label} className="divide-y overflow-hidden rounded-xl border">
      {profiles.map((profile) => <ProfileOption key={profile.key} profile={profile} name={name} checked={value === profile.key} onSelect={() => onChange(profile.key)} />)}
    </div>
  )
}
