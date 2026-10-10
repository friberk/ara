import { Link } from 'react-router-dom'
import type { EmbeddingProfile } from '@/api/types'
import { useOpenModels } from '@/hooks/queries/features'
import { useSettingsDialog } from '@/features/settings/settings-url'

/** Why a model cannot be used, and, for a local model, a link to download it; shared by Settings and a paper's index panel. */
export function UnavailableReason({ profile }: { profile: Pick<EmbeddingProfile, 'unavailable_reason' | 'local_model_key'> }) {
  const openModels = useOpenModels()
  const settings = useSettingsDialog()
  return (
    <span className="flex flex-wrap gap-x-2">
      <span>{profile.unavailable_reason ?? 'Not available on the server right now.'}</span>{' '}
      {profile.local_model_key && openModels && <Link {...settings.link('open-models', '#local-models')} className="text-foreground underline decoration-foreground/25 hover:decoration-foreground">Go to Open models</Link>}
    </span>
  )
}
