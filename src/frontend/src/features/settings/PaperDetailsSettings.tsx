import { useId } from 'react'
import type { MetadataSource } from '@/api/types'
import { providerLabels } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useMetadataSettings, useSaveMetadataSettings } from '@/hooks/queries/metadata'
import { ChoiceList, ChoiceRow, SettingsSection } from './parts'

const sources: { value: MetadataSource; about: string }[] = [
  { value: 'openalex', about: 'A free, open catalog of research from every field, run by the nonprofit OurResearch.' },
  { value: 'semantic_scholar', about: 'A free research catalog run by the Allen Institute for AI.' },
]

/** Where an uploaded PDF's bibliography is looked up. A choice saves at once; a failed save falls back to the stored one. */
export function PaperDetailsSettings() {
  const id = useId()
  const saved = useMetadataSettings()
  const save = useSaveMetadataSettings()
  const value = save.isPending ? save.variables : saved.data?.source
  return (
    <SettingsSection
      headingId={id}
      title="Paper details"
      status={save.isSuccess ? 'Saved' : ''}
      description={<p>When you upload a PDF, its title, authors, year, venue and abstract are looked up in this catalog. If the paper isn’t found there, or the catalog doesn’t answer, the other one is tried. Details you edited are never replaced. If a paper’s details come back wrong, try the other catalog.</p>}
    >
      {saved.isPending && !saved.error && <div role="status"><span className="sr-only">Loading where paper details come from…</span><Skeleton className="h-28 w-full rounded-xl" /></div>}
      <ErrorNotice error={saved.error} retry={() => void saved.refetch()} />
      {saved.data && (
        <ChoiceList labelledBy={id}>
          {sources.map((source) => (
            <ChoiceRow key={source.value} name={id} value={source.value} checked={(value ?? saved.data.source) === source.value} onSelect={() => { if (source.value !== saved.data.source) save.mutate(source.value) }} title={providerLabels[source.value]}>
              {source.about}
            </ChoiceRow>
          ))}
        </ChoiceList>
      )}
      <ErrorNotice error={save.error} />
    </SettingsSection>
  )
}
