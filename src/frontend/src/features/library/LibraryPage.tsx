import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Info, Library, Search, SearchX, Trash2, Upload, X } from 'lucide-react'
import type { Paper } from '@/api/types'
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { DocumentStatusBadge } from '@/components/feedback/DocumentStatusBadge'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { PendingMatches } from '@/components/upload/PendingMatches'
import { UploadList } from '@/components/upload/UploadList'
import { DropOverlay } from '@/components/upload/DropOverlay'
import { usePageDrop } from '@/components/upload/use-page-drop'
import { useUploads } from '@/components/upload/use-upload'
import { usePapers } from '@/hooks/queries/papers'
import { PaperByline } from '@/features/research/PaperByline'
import { countFormat, displayText, paperName } from '@/features/research/paper-format'
import { DeletePapersDialog } from './DeletePapersDialog'
import { PaperActions } from './PaperActions'

const FILTER_DELAY_MS = 250

function PaperRow({ paper, selected, onSelect }: { paper: Paper; selected: boolean; onSelect: (selected: boolean) => void }) {
  const name = paperName(paper)
  return (
    <article className="group relative flex items-start gap-3 py-5">
      {/* The checkbox and the actions sit above the stretched title link. */}
      <Checkbox className="relative z-10 mt-1" checked={selected} onCheckedChange={(value) => onSelect(value === true)} aria-label={`Select “${name}”`} />
      <div className="min-w-0 flex-1">
        <h2 className="text-base leading-snug font-semibold tracking-tight text-balance break-words">
          {/* The title link stretches over the row so the whole row opens the paper. */}
          <Link to={`/papers/${paper.id}`} className="rounded-sm underline-offset-4 group-hover:underline after:absolute after:inset-0">{name}</Link>
        </h2>
        <PaperByline authors={paper.authors} year={paper.year} className="mt-1.5">
          <DocumentStatusBadge state={paper.document_status} />
        </PaperByline>
        {displayText(paper.abstract) && <p className="mt-2 line-clamp-2 text-sm leading-6 text-pretty text-muted-foreground">{displayText(paper.abstract)}</p>}
      </div>
      <PaperActions paper={paper} className="relative z-10 -mt-0.5 -mr-2 shrink-0" />
    </article>
  )
}

/** Select all, and once papers are chosen, what can be done with them together (ARA-095). */
function SelectionBar({ papers, chosen, onChange, onDelete }: { papers: Paper[]; chosen: Paper[]; onChange: (ids: string[]) => void; onDelete: () => void }) {
  const all = chosen.length > 0 && chosen.length === papers.length
  return (
    <div className="flex min-h-12 items-center gap-3 border-b py-2">
      <Checkbox
        id="select-all-papers"
        checked={all ? true : chosen.length ? 'indeterminate' : false}
        onCheckedChange={(value) => onChange(value === true ? papers.map((paper) => paper.id) : [])}
        aria-label="Select all papers"
      />
      {chosen.length ? (
        <div role="toolbar" aria-label="Selected papers" className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-medium tabular" aria-live="polite">{countFormat.format(chosen.length)} selected</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={() => onChange([])}>Clear selection</Button>
            <Button variant="destructive" size="sm" onClick={onDelete}><Trash2 data-icon="inline-start" aria-hidden="true" />Delete…</Button>
          </div>
        </div>
      ) : (
        <label htmlFor="select-all-papers" className="text-sm text-muted-foreground">Select all</label>
      )}
    </div>
  )
}

/** Shown after a link to a paper that no longer exists brought the reader here (ARA-095). */
function MissingPaperNote({ onDismiss }: { onDismiss: () => void }) {
  return (
    <Alert role="status" className="mt-6 items-center">
      <Info aria-hidden="true" />
      <AlertDescription>That paper isn’t in your library anymore. It may have been deleted.</AlertDescription>
      <AlertAction><Button variant="ghost" size="sm" onClick={onDismiss}>Dismiss</Button></AlertAction>
    </Alert>
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
  // Only listed papers can be chosen, so a filter or a deletion never leaves hidden papers selected.
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const chosen = items.filter((paper) => selected.has(paper.id))
  const select = (id: string, on: boolean) => setSelected((current) => { const next = new Set(current); if (on) next.add(id); else next.delete(id); return next })
  const [deleting, setDeleting] = useState(false)
  const missingPaper = (location.state as { missingPaper?: boolean } | null)?.missingPaper === true
  const dismissNote = () => navigate({ pathname: location.pathname, search: location.search, hash: location.hash }, { replace: true, state: null })

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
      {missingPaper && <MissingPaperNote onDismiss={dismissNote} />}
      {uploadOpen && <AddPdfs onChoose={choose} onClose={closeUpload} />}
      <UploadList uploads={uploads} className="mt-6" />
      <PendingMatches hidden={uploads.items.flatMap((item) => (item.accepted ? [item.accepted.paper_id] : []))} className="mt-6" />

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
          <>
            <SelectionBar papers={items} chosen={chosen} onChange={(ids) => setSelected(new Set(ids))} onDelete={() => setDeleting(true)} />
            <ul aria-label="Papers" className="divide-y">
              {items.map((paper) => <li key={paper.id}><PaperRow paper={paper} selected={selected.has(paper.id)} onSelect={(on) => select(paper.id, on)} /></li>)}
            </ul>
          </>
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

      <DeletePapersDialog
        papers={chosen}
        open={deleting && chosen.length > 0}
        onOpenChange={setDeleting}
        onDeleted={(ids) => setSelected((current) => new Set([...current].filter((id) => !ids.includes(id))))}
      />
      <DropOverlay show={dragging} label="Drop PDFs to add them to your library" />
    </div>
  )
}
