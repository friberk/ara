import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Library, Search, SearchX, Upload, X } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { UploadList } from '@/components/upload/UploadList'
import { DropOverlay } from '@/components/upload/DropOverlay'
import { usePageDrop } from '@/components/upload/use-page-drop'
import { useUploads } from '@/components/upload/use-upload'
import { usePapers } from '@/hooks/queries/papers'
import { PaperByline } from '@/features/research/PaperByline'
import { countFormat, displayText, paperName } from '@/features/research/paper-format'

const FILTER_DELAY_MS = 250

function PaperRow({ paper }: { paper: Paper }) {
  return (
    <article className="group relative py-5">
      <h2 className="text-base leading-snug font-semibold tracking-tight text-balance break-words">
        {/* The title link stretches over the row so the whole row opens the paper. */}
        <Link to={`/papers/${paper.id}`} className="rounded-sm underline-offset-4 group-hover:underline after:absolute after:inset-0">{paperName(paper)}</Link>
      </h2>
      <PaperByline authors={paper.authors} year={paper.year} className="mt-1.5">
        <DocumentStatusBadge state={paper.document_status} />
      </PaperByline>
      {displayText(paper.abstract) && <p className="mt-2 line-clamp-2 text-sm leading-6 text-pretty text-muted-foreground">{displayText(paper.abstract)}</p>}
    </article>
  )
}

/** Opened by /library#upload links: where to drop PDFs, with a button for the picker. */
function AddPdfs({ onChoose, onClose }: { onChoose: () => void; onClose: () => void }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="relative mt-6 grid justify-items-center gap-2 rounded-xl border border-dashed px-6 py-8 text-center">
      <Button variant="ghost" size="icon-sm" aria-label="Close" className="absolute top-2 right-2 text-muted-foreground" onClick={onClose}><X /></Button>
      <span className="flex size-10 items-center justify-center rounded-full bg-muted"><Upload className="size-4" aria-hidden="true" /></span>
      <h2 id={headingId} className="text-sm font-medium">Add PDFs</h2>
      <p className="max-w-sm text-xs text-pretty text-muted-foreground">Drop PDFs anywhere on this page, or choose them. Each becomes its own paper. Text-based PDFs, up to 25 MB each.</p>
      <Button size="sm" variant="outline" className="mt-1" onClick={onChoose}>Choose PDFs</Button>
    </section>
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

/**
 * Saved and uploaded papers. The filter lives in ?q= and the upload area in #upload, so both survive reloads and links.
 * PDFs dropped anywhere on the page, or picked with Upload PDF, upload at once, each with its own row.
 */
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
  const closeUpload = () => navigate({ pathname: location.pathname, search: location.search, hash: '' }, { replace: true })
  const picker = useRef<HTMLInputElement>(null)
  const uploads = useUploads()
  const addFiles = (files: File[]) => { uploads.add(files); if (uploadOpen) closeUpload() }
  const dragging = usePageDrop(addFiles)
  const choose = () => picker.current?.click()
  const clearFilter = () => { setText(''); setSearchParams({}, { replace: true }) }
  const count = `${countFormat.format(items.length)}${papers.hasNextPage ? '+' : ''} ${items.length === 1 && !papers.hasNextPage ? 'paper' : 'papers'}`

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
        <div className="grid gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Library</h1>
          <p className="text-sm text-muted-foreground" aria-live="polite">{papers.data ? count : ' '}</p>
        </div>
        <Button onClick={choose}><Upload aria-hidden="true" />Upload PDF</Button>
        <input ref={picker} type="file" multiple accept="application/pdf,.pdf" aria-label="PDF files" tabIndex={-1} className="sr-only" onChange={(event) => { addFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
      </header>
      {uploadOpen && <AddPdfs onChoose={choose} onClose={closeUpload} />}
      <UploadList uploads={uploads} className="mt-6" />

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
            action={<div className="flex flex-wrap justify-center gap-2"><Button asChild><Link to="/">Search papers</Link></Button><Button variant="outline" onClick={choose}>Upload a PDF</Button></div>}
          >
            Save papers from a search or upload a PDF. They stay here between visits, ready for summaries and questions.
          </EmptyState>
        ))}
        {items.length > 0 && (
          <ul aria-label="Papers" className="divide-y">
            {items.map((paper) => <li key={paper.id}><PaperRow paper={paper} /></li>)}
          </ul>
        )}
        {papers.isFetchNextPageError && <ErrorNotice error={papers.error} retry={() => void papers.fetchNextPage()} className="mt-2" />}
        {papers.hasNextPage && !papers.isFetchNextPageError && (
          <div className="flex justify-center border-t pt-6">
            <Button variant="outline" disabled={papers.isFetchingNextPage} aria-busy={papers.isFetchingNextPage} onClick={() => void papers.fetchNextPage()}>
              {papers.isFetchingNextPage && <Spinner aria-hidden="true" />}Load more
            </Button>
          </div>
        )}
      </div>

      <DropOverlay show={dragging} label="Drop PDFs to add them to your library" />
    </div>
  )
}
