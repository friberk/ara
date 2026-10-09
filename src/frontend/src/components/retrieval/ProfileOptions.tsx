import { useId } from 'react'
import { Link } from 'react-router-dom'
import type { EmbeddingProfile } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const statusBadges: Record<EmbeddingProfile['status'], { label: string; tone: string }> = {
  available: { label: 'Available', tone: 'bg-success-muted text-success' },
  unavailable: { label: 'Unavailable', tone: 'bg-muted text-muted-foreground' },
}

function OptionRow({ name, value, checked, onSelect, title, badge, children }: { name: string; value: string; checked: boolean; onSelect: () => void; title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  const id = useId()
  return (
    <label htmlFor={`${id}-radio`} className={cn('flex cursor-pointer gap-3 px-4 py-3.5 transition-colors hover:bg-muted/50', checked && 'bg-muted/60 hover:bg-muted/60')}>
      <input id={`${id}-radio`} type="radio" name={name} value={value} checked={checked} onChange={onSelect} aria-labelledby={`${id}-name`} aria-describedby={`${id}-details`} className="mt-0.5 size-4 shrink-0 accent-foreground" />
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

/** A local model's reason and a way to install it; shared by the Settings list and a paper's index panel. */
export function UnavailableReason({ profile }: { profile: EmbeddingProfile }) {
  return (
    <span className="flex flex-wrap gap-x-2">
      <span>{profile.unavailable_reason ?? 'Not available on the server right now.'}</span>
      {profile.local_model_key && <Link to="/settings#local-models" className="text-foreground underline decoration-foreground/25 hover:decoration-foreground">Go to Local models</Link>}
    </span>
  )
}

/**
 * Radio list of search models in the style of the default-model list. With defaultChoice, a first "Use default"
 * row stands for following the Settings default (value null).
 */
export function ProfileOptions({ profiles, value, onChange, label, defaultChoice }: { profiles: EmbeddingProfile[]; value: string | null; onChange: (key: string | null) => void; label: string; defaultChoice?: string }) {
  const name = useId()
  return (
    <div role="radiogroup" aria-label={label} className="divide-y overflow-hidden rounded-xl border">
      {defaultChoice !== undefined && <OptionRow name={name} value="" checked={value === null} onSelect={() => onChange(null)} title="Use default">{defaultChoice}</OptionRow>}
      {profiles.map((profile) => {
        const badge = statusBadges[profile.status]
        return (
          <OptionRow key={profile.key} name={name} value={profile.key} checked={value === profile.key} onSelect={() => onChange(profile.key)} title={profile.display_name} badge={<Badge variant="secondary" className={cn('font-normal', badge.tone)}>{badge.label}</Badge>}>
            <span className="font-mono break-all">{profile.model_id}</span>
            {/* Still selectable: the server accepts it and the paper searches by keyword until the model is ready. */}
            {profile.status === 'unavailable' && <UnavailableReason profile={profile} />}
          </OptionRow>
        )
      })}
    </div>
  )
}
