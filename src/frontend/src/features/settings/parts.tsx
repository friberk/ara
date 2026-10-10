import { useId } from 'react'
import { cn } from '@/lib/utils'

/**
 * One setting: a heading that names it (`headingId` labels its control), a sentence on what it changes, an optional
 * control at the right, and what follows. `status` confirms a save beside the heading, where the change was made.
 */
export function SettingsSection({ headingId, title, description, control, status, children }: { headingId: string; title: string; description?: React.ReactNode; control?: React.ReactNode; status?: React.ReactNode; children?: React.ReactNode }) {
  const descriptionId = useId()
  return (
    <section aria-labelledby={headingId} aria-describedby={description ? descriptionId : undefined} className="grid gap-4 py-6 first:pt-1">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="grid min-w-[min(100%,15rem)] flex-1 gap-1">
          <div className="flex items-baseline gap-2">
            <h4 id={headingId} className="text-sm font-medium">{title}</h4>
            <span role="status" className="text-xs text-muted-foreground">{status}</span>
          </div>
          {description && <div id={descriptionId} className="grid max-w-prose gap-2 text-sm text-pretty text-muted-foreground">{description}</div>}
        </div>
        {control}
      </div>
      {children}
    </section>
  )
}

/** A bordered list of choices with a single answer, one row each. */
export function ChoiceList({ label, labelledBy, children }: { label?: string; labelledBy?: string; children: React.ReactNode }) {
  return <div role="radiogroup" aria-label={label} aria-labelledby={labelledBy} className="divide-y overflow-hidden rounded-xl border">{children}</div>
}

/**
 * One choice: a radio, its name, a short note at the right (such as Default) and its details, which screen readers
 * hear as the radio's description. A disabled row keeps its details readable, including how to make it usable.
 */
export function ChoiceRow({ name, value, checked, disabled, onSelect, title, note, children }: { name: string; value: string; checked: boolean; disabled?: boolean; onSelect: () => void; title: string; note?: React.ReactNode; children?: React.ReactNode }) {
  const id = useId()
  return (
    <label htmlFor={`${id}-radio`} className={cn('flex gap-3 px-4 py-3 transition-colors', disabled ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-muted/50', checked && 'bg-muted/60 hover:bg-muted/60')}>
      <input id={`${id}-radio`} type="radio" name={name} value={value} checked={checked} disabled={disabled} onChange={onSelect} aria-labelledby={`${id}-name`} aria-describedby={children ? `${id}-details` : undefined} className="mt-0.5 size-4 shrink-0 accent-foreground disabled:cursor-not-allowed disabled:opacity-50" />
      <span className="grid min-w-0 flex-1 gap-1">
        <span className="flex items-baseline justify-between gap-3">
          <span id={`${id}-name`} className={cn('text-sm font-medium', disabled && 'text-muted-foreground')}>{title}</span>
          {note}
        </span>
        {children && <span id={`${id}-details`} className="grid gap-1 text-sm text-pretty text-muted-foreground">{children}</span>}
      </span>
    </label>
  )
}
