import { useId, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Download, EllipsisVertical, ExternalLink, FileUp, MessageSquareWarning, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { downloadUrl } from '@/api/client'
import { providerLabels, type DocumentDetail, type Paper, type PdfRemovalPreview, type UploadAccepted } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
import { formatSize } from '@/components/upload/validate-pdf'
import { countFormat } from '@/features/research/paper-format'
import { useDocument, usePdfRemovalPreview, useRemovePdf } from '@/hooks/queries/documents'

const count = (value: number, one: string, many: string) => `${countFormat.format(value)} ${value === 1 ? one : many}`

/** "Uploaded", or the provider a stored copy was downloaded from (ARA-087). */
function sourceLabel(acquisition: DocumentDetail['acquisition']) {
  const provider = acquisition?.provider
  return provider === 'openalex' || provider === 'semantic_scholar' ? `Downloaded from ${providerLabels[provider]}` : 'Uploaded'
}

/** The menu's non-interactive header: the file, its pages and size, and where it came from. */
function FileFacts({ documentId, pages }: { documentId: string; pages: number | null }) {
  const file = useDocument(documentId)
  if (file.isPending) return <div role="status" className="grid gap-1.5 py-0.5"><span className="sr-only">Loading PDF details…</span><Skeleton className="h-4 w-40" /><Skeleton className="h-3 w-24" /></div>
  if (!file.data) return <span>PDF details are unavailable</span>
  const pageCount = pages ?? file.data.page_count
  return (
    <div className="grid min-w-0 gap-0.5">
      <span className="truncate text-sm font-medium text-popover-foreground" title={file.data.file_name}>{file.data.file_name}</span>
      <span className="tabular">{[pageCount ? count(pageCount, 'page', 'pages') : null, formatSize(file.data.byte_size)].filter(Boolean).join(' · ')}</span>
      <span>{sourceLabel(file.data.acquisition)}</span>
    </div>
  )
}

/** Opens the existing upload in a dialog; the new PDF becomes the paper's current one, as an upload always has. */
function ReplacePdfDialog({ paper, onClose }: { paper: Paper; onClose: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  function accepted(upload: UploadAccepted) {
    // The same file again changes nothing, and the dropzone says so; otherwise the reader follows the new PDF.
    if (upload.duplicate) return
    navigate(location, { replace: true, state: { ...(location.state as object | null), upload: { jobId: upload.job_id } } })
    onClose()
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Replace the PDF</DialogTitle>
          <DialogDescription>The new PDF becomes the one you read and ask about. Earlier answers keep citing the PDF they used.</DialogDescription>
        </DialogHeader>
        <UploadDropzone paperId={paper.id} title="Drop the new PDF here, or choose one" description="Text-based PDF, up to 25 MB." onAccepted={accepted} />
      </DialogContent>
    </Dialog>
  )
}

/** What removing changes, in the order a reader meets it: the reader, the files, summaries, answers, then work. */
function effects(preview: PdfRemovalPreview): string[] {
  const earlier = preview.pdfs - 1
  const chats = preview.chats.length
  return [
    'The reader goes back to uploading a PDF.',
    ...(earlier > 0 ? [`${count(earlier, 'earlier version', 'earlier versions')} of the PDF ${earlier === 1 ? 'is' : 'are'} deleted too.`] : []),
    ...(preview.summaries ? [`${count(preview.summaries, 'summary', 'summaries')} of this PDF ${preview.summaries === 1 ? 'is' : 'are'} deleted.`] : []),
    ...(chats ? [
      'Earlier answers keep their quoted passages, but their page links won’t open.',
      `${count(chats, 'conversation', 'conversations')} that used it ${chats === 1 ? 'stays' : 'stay'} readable but can’t take new questions.`,
    ] : []),
    ...(preview.active_jobs ? [`${count(preview.active_jobs, 'background task', 'background tasks')} for this PDF ${preview.active_jobs === 1 ? 'stops' : 'stop'}.`] : []),
  ]
}

/**
 * Confirms removing the paper's PDF (ARA-097). It states what happens from the server's preview, keeps Cancel focused,
 * and waits while a conversation that uses the PDF is still answering.
 */
function RemovePdfDialog({ paper, reader, onClose }: { paper: Paper; reader: HTMLElement | null; onClose: () => void }) {
  const listId = useId()
  const preview = usePdfRemovalPreview(paper.id, true)
  const removal = useRemovePdf(paper.id)
  // Set before the dialog closes, which can happen before it renders again.
  const removed = useRef(false)
  const data = preview.data
  return (
    <AlertDialog open onOpenChange={(open) => { if (!open && !removal.isPending) onClose() }}>
      {/* After a removal the menu that held focus goes with the PDF, so focus moves to the reader. */}
      <AlertDialogContent className="sm:max-w-md" onCloseAutoFocus={(event) => { if (removed.current && reader) { event.preventDefault(); reader.focus() } }}>
        <AlertDialogHeader>
          <AlertDialogTitle>Remove this PDF?</AlertDialogTitle>
          <AlertDialogDescription className="break-words">{paper.file_name ? `“${paper.file_name}” is deleted. This can’t be undone.` : 'The PDF is deleted. This can’t be undone.'}</AlertDialogDescription>
        </AlertDialogHeader>
        {preview.isPending && <div role="status" className="grid gap-2"><span className="sr-only">Checking what changes…</span><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></div>}
        <ErrorNotice error={preview.error} retry={() => void preview.refetch()} />
        {data && (
          <div className="grid gap-3 text-sm">
            <div className="grid gap-1.5">
              <p id={listId} className="font-medium">What happens</p>
              <ul aria-labelledby={listId} className="grid list-disc gap-1 pl-5 text-pretty text-muted-foreground marker:text-muted-foreground/60">
                {effects(data).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            {data.answering && (
              <Alert>
                <MessageSquareWarning aria-hidden="true" />
                <AlertDescription>A conversation that uses this PDF is still writing an answer. Remove the PDF when it finishes.</AlertDescription>
              </Alert>
            )}
          </div>
        )}
        <ErrorNotice error={removal.error} />
        <AlertDialogFooter>
          <AlertDialogCancel disabled={removal.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={!data || data.answering || removal.isPending}
            onClick={(event) => {
              // The dialog stays open while removing, so a failure is shown where it happened.
              event.preventDefault()
              removal.mutate(undefined, { onSuccess: () => { removed.current = true; toast.success('PDF removed'); onClose() } })
            }}
          >
            {removal.isPending ? 'Removing…' : 'Remove PDF'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/**
 * The reader's PDF menu (ARA-097): the file's facts, then open or download it. For the paper's current PDF it can also
 * be replaced, or removed so that the reader returns to its upload state.
 */
export function PdfMenu({ documentId, pages, managed }: { documentId: string; pages: number | null; managed?: Paper }) {
  const [dialog, setDialog] = useState<'replace' | 'remove' | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [hint, setHint] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  // The reader around this menu, found while the menu is still there.
  const [reader, setReader] = useState<HTMLElement | null>(null)
  const file = useDocument(documentId)
  return (
    <>
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        {/* The menu opens on pointerdown, so the click that would cancel a pending tooltip never lands; keep it shut. */}
        <Tooltip open={hint && !menuOpen} onOpenChange={setHint}>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button ref={trigger} type="button" variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-foreground" aria-label="PDF options"><EllipsisVertical aria-hidden="true" /></Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom">PDF options</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuLabel className="font-normal"><FileFacts documentId={documentId} pages={pages} /></DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild><a href={downloadUrl(documentId)} target="_blank" rel="noreferrer"><ExternalLink aria-hidden="true" />Open original</a></DropdownMenuItem>
          <DropdownMenuItem asChild><a href={downloadUrl(documentId)} download={file.data?.file_name ?? ''}><Download aria-hidden="true" />Download</a></DropdownMenuItem>
          {managed && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setDialog('replace')}><FileUp aria-hidden="true" />Replace PDF…</DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={() => { setReader(trigger.current?.closest<HTMLElement>('section[aria-label="PDF reader"]') ?? null); setDialog('remove') }}><Trash2 aria-hidden="true" />Remove PDF…</DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {managed && dialog === 'replace' && <ReplacePdfDialog paper={managed} onClose={() => setDialog(null)} />}
      {managed && dialog === 'remove' && <RemovePdfDialog paper={managed} reader={reader} onClose={() => setDialog(null)} />}
    </>
  )
}
