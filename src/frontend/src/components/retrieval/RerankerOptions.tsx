import { useId } from 'react'
import type { Reranker } from '@/api/types'
import { OptionRow, StatusBadge, UnavailableReason } from './ProfileOptions'

// What each kind of reranker costs, by provider; the models themselves come from the server's catalog.
const tradeoffs: Record<Reranker['provider'], string> = {
  openai: 'Fast, with a small cost per answer.',
  ollama: 'Private. Adds about 10 seconds to each answer.',
}

/**
 * Radio list of the reranker profiles the server lists, then Off (value null). A reranker that is not installed
 * cannot be chosen; its reason says how to install it.
 */
export function RerankerOptions({ rerankers, value, onChange, label }: { rerankers: Reranker[]; value: string | null; onChange: (key: string | null) => void; label: string }) {
  const name = useId()
  return (
    <div role="radiogroup" aria-label={label} className="divide-y overflow-hidden rounded-xl border">
      {rerankers.map((reranker) => (
        <OptionRow key={reranker.key} name={name} value={reranker.key} checked={value === reranker.key} onSelect={() => onChange(reranker.key)} title={reranker.display_name} badge={<StatusBadge status={reranker.status} />} disabled={reranker.status !== 'available'}>
          {/* The spaces keep the details apart when read as one description; the grid drops them visually. */}
          <span className="font-mono break-all">{reranker.model_id}</span>{' '}
          <span>{tradeoffs[reranker.provider]}</span>{' '}
          {reranker.status !== 'available' && <UnavailableReason profile={reranker} />}
        </OptionRow>
      ))}
      <OptionRow name={name} value="" checked={value === null} onSelect={() => onChange(null)} title="Off">Passages are used in the order search finds them.</OptionRow>
    </div>
  )
}
