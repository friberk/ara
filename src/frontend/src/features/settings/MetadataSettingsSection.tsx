import { useId } from 'react'
import type { MetadataSource } from '@/api/types'
import { providerLabels } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useMetadataSettings, useSaveMetadataSettings } from '@/hooks/queries/metadata'
import { segmentedGroup, segmentedItem } from './segmented'

const sources: MetadataSource[] = ['openalex', 'semantic_scholar']

/** Where uploaded PDFs are looked up for their bibliography. A choice saves at once, like the theme. */
export function MetadataSettingsSection() {
  const headingId = useId()
  const saved = useMetadataSettings()
  const save = useSaveMetadataSettings()
  // While a choice saves it shows as chosen; a failed save falls back to the stored one.
  const value = save.isPending ? save.variables : saved.data?.source
  return (
    <section aria-labelledby={headingId} className="grid gap-4">
      <div className="grid gap-1">
        <h2 id={headingId} className="text-base font-semibold tracking-tight">Metadata source</h2>
        <p className="text-sm text-pretty text-muted-foreground">After you upload a PDF, its title, authors, year, venue and abstract are looked up here, and the other catalog is tried when this one is busy. The lookup never replaces details you edited.</p>
      </div>
      {saved.isPending && !saved.error && <div role="status"><span className="sr-only">Loading the metadata source…</span><Skeleton className="h-8 w-64 rounded-lg" /></div>}
      <ErrorNotice error={saved.error} retry={() => void saved.refetch()} />
      {saved.data && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-labelledby={headingId} value={value ?? saved.data.source} disabled={save.isPending} onValueChange={(next) => { if (next && next !== saved.data.source) save.mutate(next as MetadataSource) }} className={segmentedGroup}>
            {sources.map((source) => <ToggleGroupItem key={source} value={source} className={segmentedItem}>{providerLabels[source]}</ToggleGroupItem>)}
          </ToggleGroup>
          <p role="status" className="text-sm text-muted-foreground">{save.isSuccess ? 'Metadata source saved.' : ''}</p>
        </div>
      )}
      <ErrorNotice error={save.error} />
    </section>
  )
}
