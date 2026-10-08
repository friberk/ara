import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, SearchX } from 'lucide-react'
import { ApiError } from '@/api/client'
import { providerLabels, type Provider } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Composer } from '@/components/composer/Composer'
import { ProviderSwitcher } from '@/components/composer/ProviderSwitcher'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { searchHref } from '@/components/shell/recent-items'
import { uniqueHits, useRecordSearch, useSearch, type SearchParams } from '@/hooks/queries/search'
import { PaperCard } from './PaperCard'
import { countFormat, otherProvider } from './paper-format'

function readProvider(value: string | null): Provider { return value === 'semantic_scholar' ? 'semantic_scholar' : 'openalex' }

/** A rate-limited provider is named with the way out: wait, or ask the other provider. */
function searchError(error: unknown, provider: Provider) {
  if (error instanceof ApiError && error.status === 429) {
    return new Error(`${providerLabels[provider]} is busy right now. Try again in a moment, or search ${providerLabels[otherProvider(provider)]} instead.`)
  }
  return error
}

function ResultSkeleton() {
  return (
    <div className="grid gap-2.5 py-6">
      <Skeleton className="h-5 w-4/5" />
      <Skeleton className="h-4 w-2/5" />
      <div className="mt-1.5 grid gap-2"><Skeleton className="h-3.5 w-full" /><Skeleton className="h-3.5 w-11/12" /><Skeleton className="h-3.5 w-3/5" /></div>
    </div>
  )
}

function SearchThread({ params, onSearch }: { params: SearchParams; onSearch: (next: SearchParams) => void }) {
  const search = useSearch(params)
  const hits = uniqueHits(search.data?.pages)
  const total = search.data?.pages[0]?.total
  const label = providerLabels[params.provider]
  const other = otherProvider(params.provider)
  let summary = `Searching ${label}…`
  if (search.data) summary = total != null ? `${countFormat.format(total)} ${total === 1 ? 'result' : 'results'} from ${label}` : `${countFormat.format(hits.length)} ${hits.length === 1 ? 'paper' : 'papers'} from ${label}`
  else if (search.isError) summary = `Search on ${label} did not finish`
  return (
    <>
      <header className="grid gap-1.5 pb-2">
        <h1 className="text-2xl font-semibold tracking-tight text-balance break-words">{params.q}</h1>
        <p className="text-sm text-muted-foreground" aria-live="polite">{summary}</p>
      </header>
      {search.isPending && (
        <div role="status" className="divide-y">
          <span className="sr-only">Searching {label}…</span>
          {Array.from({ length: 3 }, (_, index) => <ResultSkeleton key={index} />)}
        </div>
      )}
      {!search.data && <ErrorNotice error={searchError(search.error, params.provider)} retry={() => void search.refetch()} className="mt-4" />}
      {search.data && !hits.length && (
        <EmptyState icon={SearchX} title="No papers found" className="mt-8" action={<Button variant="outline" onClick={() => onSearch({ q: params.q, provider: other })}>Search {providerLabels[other]} instead</Button>}>
          Try a broader topic with fewer words, or search {providerLabels[other]} instead.
        </EmptyState>
      )}
      {hits.length > 0 && (
        <ol aria-label="Search results" className="divide-y">
          {hits.map((hit) => <li key={`${hit.provider}:${hit.external_id}`}><PaperCard hit={hit} /></li>)}
        </ol>
      )}
      {search.data && <ErrorNotice error={searchError(search.error, params.provider)} retry={() => void search.fetchNextPage()} className="mt-2" />}
      {search.hasNextPage && !search.isFetchNextPageError && (
        <div className="flex justify-center border-t pt-6">
          <Button variant="outline" disabled={search.isFetchingNextPage} aria-busy={search.isFetchingNextPage} onClick={() => void search.fetchNextPage()}>
            {search.isFetchingNextPage && <Spinner aria-hidden="true" />}Load more
          </Button>
        </div>
      )}
    </>
  )
}

function SearchComposer({ initial, onSearch }: { initial: SearchParams | null; onSearch: (next: SearchParams) => void }) {
  const [text, setText] = useState(initial?.q ?? '')
  const [provider, setProvider] = useState<Provider>(initial?.provider ?? 'openalex')
  return (
    <div className="sticky bottom-0 z-10 bg-background px-4 pt-1 pb-4 before:pointer-events-none before:absolute before:inset-x-0 before:-top-6 before:h-6 before:bg-linear-to-t before:from-background before:to-transparent sm:px-6">
      <Composer
        value={text}
        onValueChange={setText}
        onSubmit={() => onSearch({ q: text.trim(), provider })}
        label="Research topic"
        placeholder={initial ? 'Refine search' : 'Search papers by topic, title or research question'}
        submitLabel="Search papers"
        maxLength={300}
        autoFocus={!initial}
        leading={<ProviderSwitcher value={provider} onChange={setProvider} />}
        className="mx-auto max-w-3xl"
      />
    </div>
  )
}

/** /search?q=&provider= : a research thread of paper rows with a docked composer to refine it. Deep links run on load. */
export default function SearchPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const record = useRecordSearch()
  const q = searchParams.get('q')?.trim() ?? ''
  const provider = readProvider(searchParams.get('provider'))
  const params = q ? { q, provider } : null
  // History is recorded only for explicit submissions; loading a link never writes.
  function onSearch(next: SearchParams) {
    record.mutate(next)
    navigate(searchHref({ query: next.q, provider: next.provider }))
  }
  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto w-full max-w-3xl flex-1 px-4 pt-6 pb-10 sm:px-6 sm:pt-10">
        {params ? (
          <SearchThread key={`${params.provider}:${params.q}`} params={params} onSearch={onSearch} />
        ) : (
          <div className="grid gap-2 pt-[10vh] text-center">
            <Search className="mx-auto mb-2 size-5 text-muted-foreground" aria-hidden="true" />
            <h1 className="text-2xl font-semibold tracking-tight">Search the literature</h1>
            <p className="mx-auto max-w-md text-sm text-pretty text-muted-foreground">Enter a topic below. Each result shows the title, authors, year and abstract, with links to the paper.</p>
          </div>
        )}
      </div>
      <SearchComposer key={params ? `${params.provider}:${params.q}` : 'new'} initial={params} onSearch={onSearch} />
    </div>
  )
}
