import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Library, Search, SearchX, Upload } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
import { usePapers } from '@/hooks/queries/papers'
import { PaperByline } from '@/features/research/PaperByline'
import { countFormat } from '@/features/research/paper-format'

const FILTER_DELAY_MS = 250

function PaperRow({ paper }: { paper: Paper }) {
  return (
    <article className="group relative py-5">
      <h2 className="text-base leading-snug font-semibold tracking-tight text-balance break-words">
        {/* The title link stretches over the row so the whole row opens the paper. */}
        <Link to={`/papers/${paper.id}`} className="rounded-sm underline-offset-4 group-hover:underline after:absolute after:inset-0">{paper.title?.trim() || 'Untitled paper'}</Link>
      </h2>
      <PaperByline authors={paper.authors} year={paper.year} className="mt-1.5">
        <DocumentStatusBadge state={paper.document_status} />
      </PaperByline>
      {paper.abstract?.trim() && <p className="mt-2 line-clamp-2 text-sm leading-6 text-pretty text-muted-foreground">{paper.abstract.trim()}</p>}
    </article>
  )
}

function RowSkeleton() {
  return (
    <div className="grid gap-2.5 py-5">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-3.5 w-full" />
    </div>
  )
}

/** Saved and uploaded papers. The filter lives in ?q= and the upload dialog in #upload, so both survive reloads and links. */
export default function LibraryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const filter = searchParams.get('q')?.trim() ?? ''
  const [text, setText] = useState(filter)
  // Follow the URL when it changes from outside the field (back, forward, Clear filter).
  const [syncedFilter, setSyncedFilter] = useState(filter)
  if (filter !== syncedFilter) {
    setSyncedFilter(filter)
    if (text.trim() !== filter) setText(filter)
  }
  useEffect(() => {
    const next = text.trim()
    if (next === filter) return
    const timer = window.setTimeout(() => setSearchParams(next ? { q: next } : {}, { replace: true }), FILTER_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [text, filter, setSearchParams])

  const papers = usePapers(filter)
  const items = papers.data?.pages.flatMap((page) => page.items) ?? []
  const uploadOpen = location.hash === '#upload'
  const setUploadOpen = (open: boolean) => navigate({ pathname: location.pathname, search: location.search, hash: open ? '#upload' : '' }, { replace: true })
  const clearFilter = () => { setText(''); setSearchParams({}, { replace: true }) }
  const count = `${countFormat.format(items.length)}${papers.hasNextPage ? '+' : ''} ${items.length === 1 && !papers.hasNextPage ? 'paper' : 'papers'}`

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="grid gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Library</h1>
          <p className="text-sm text-muted-foreground" aria-live="polite">{papers.data ? count : ' '}</p>
        </div>
        <Button onClick={() => setUploadOpen(true)}><Upload aria-hidden="true" />Upload PDF</Button>
      </header>

      <InputGroup className="mt-8 h-9">
        <InputGroupAddon><Search aria-hidden="true" /></InputGroupAddon>
        <InputGroupInput type="search" aria-label="Filter library" placeholder="Filter by title" maxLength={300} value={text} onChange={(event) => setText(event.target.value)} />
      </InputGroup>

      <div className="mt-2">
        {papers.isPending && <div role="status" className="divide-y"><span className="sr-only">Loading your library…</span>{Array.from({ length: 3 }, (_, index) => <RowSkeleton key={index} />)}</div>}
        {!papers.data && <ErrorNotice error={papers.error} retry={() => void papers.refetch()} className="mt-4" />}
        {papers.data && !items.length && (filter ? (
          <EmptyState icon={SearchX} title={`No papers match “${filter}”`} className="mt-10" action={<Button variant="outline" onClick={clearFilter}>Clear filter</Button>}>
            Try another word from the title, or clear the filter to see every paper.
          </EmptyState>
        ) : (
          <EmptyState
            icon={Library}
            title="Your library is empty"
            className="mt-10"
            action={<div className="flex flex-wrap justify-center gap-2"><Button asChild><Link to="/">Search papers</Link></Button><Button variant="outline" onClick={() => setUploadOpen(true)}>Upload a PDF</Button></div>}
          >
            Save papers from a search or upload a PDF. They stay here between visits, ready for summaries and questions.
          </EmptyState>
        ))}
        {items.length > 0 && (
          <ul aria-label="Papers" className="divide-y">
            {items.map((paper) => <li key={paper.id}><PaperRow paper={paper} /></li>)}
          </ul>
        )}
        {papers.data && <ErrorNotice error={papers.error} retry={() => void papers.fetchNextPage()} className="mt-2" />}
        {papers.hasNextPage && !papers.isFetchNextPageError && (
          <div className="flex justify-center border-t pt-6">
            <Button variant="outline" disabled={papers.isFetchingNextPage} aria-busy={papers.isFetchingNextPage} onClick={() => void papers.fetchNextPage()}>
              {papers.isFetchingNextPage && <Spinner aria-hidden="true" />}Load more
            </Button>
          </div>
        )}
      </div>

      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Upload a paper</DialogTitle>
            <DialogDescription>We read the title, authors, year and abstract from the PDF, then prepare it for summaries and questions.</DialogDescription>
          </DialogHeader>
          <UploadDropzone />
        </DialogContent>
      </Dialog>
    </div>
  )
}
