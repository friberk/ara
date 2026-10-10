import { useId } from 'react'
import { MessageSquareWarning } from 'lucide-react'
import { toast } from 'sonner'
import type { DeletionPreview } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useDeletePapers, useDeletionPreview } from '@/hooks/queries/papers'
import { countFormat, paperName } from '@/features/research/paper-format'

export type DeletionTarget = { id: string; title: string | null; file_name?: string | null }

const count = (value: number, one: string, many: string) => `${countFormat.format(value)} ${value === 1 ? one : many}`
const quoted = (titles: string[]) => {
  const shown = titles.slice(0, 3).map((title) => `“${title}”`)
  const more = titles.length - shown.length
  return more > 0 ? `${shown.join(', ')} and ${countFormat.format(more)} more` : shown.join(', ')
}

/** What goes, in the order a reader thinks of it: the papers, their files, summaries, then chats. */
function removedItems(preview: DeletionPreview, single: boolean): string[] {
  const papers = single ? 'The paper and its details' : `${count(preview.papers.length, 'paper', 'papers')} and their details`
  const chats = preview.deleted_chats
  return [
    papers,
    ...(preview.pdfs ? [`${count(preview.pdfs, 'PDF', 'PDFs')}, with their text and search index`] : []),
    ...(preview.summaries ? [count(preview.summaries, 'summary', 'summaries')] : []),
    ...(chats.length ? [`${count(chats.length, 'conversation', 'conversations')} about only ${single ? 'this paper' : 'these papers'}: ${quoted(chats.map((chat) => chat.title))}`] : []),
  ]
}

function keptNote(preview: DeletionPreview, single: boolean): string | null {
  const kept = preview.updated_chats.length
  if (!kept) return null
  const lost = single ? 'this one' : 'the deleted ones'
  return kept === 1
    ? `1 conversation that includes other papers keeps them and loses ${lost}. Its earlier answers stay readable.`
    : `${countFormat.format(kept)} conversations that include other papers keep them and lose ${lost}. Their earlier answers stay readable.`
}

function PreviewSkeleton() {
  return (
    <div role="status" className="grid gap-2">
      <span className="sr-only">Checking what will be deleted…</span>
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-3/5" />
    </div>
  )
}

/**
 * Confirms deleting one or several papers (ARA-095). It lists exactly what goes, from the server's preview, and
 * nothing is deleted until the destructive button, which names what it does, is pressed.
 */
export function DeletePapersDialog({ papers, open, onOpenChange, onDeleted }: { papers: DeletionTarget[]; open: boolean; onOpenChange: (open: boolean) => void; onDeleted?: (ids: string[]) => void }) {
  const listId = useId()
  const ids = papers.map((paper) => paper.id)
  const single = papers.length === 1
  const preview = useDeletionPreview(ids, open)
  const remove = useDeletePapers()
  const name = single ? paperName(papers[0]!) : ''
  const confirm = single ? 'Delete paper' : `Delete ${countFormat.format(papers.length)} papers`
  const data = preview.data
  const kept = data && keptNote(data, single)
  return (
    <AlertDialog open={open} onOpenChange={(next) => { if (!remove.isPending) onOpenChange(next) }}>
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="break-words">{single ? `Delete “${name}”?` : `Delete ${countFormat.format(papers.length)} papers?`}</AlertDialogTitle>
          <AlertDialogDescription>This can’t be undone.</AlertDialogDescription>
        </AlertDialogHeader>
        {preview.isPending && <PreviewSkeleton />}
        <ErrorNotice error={preview.error} retry={() => void preview.refetch()} />
        {data && (
          <div className="grid gap-3 text-sm">
            <div className="grid gap-1.5">
              <p id={listId} className="font-medium">What will be deleted</p>
              <ul aria-labelledby={listId} className="grid list-disc gap-1 pl-5 text-pretty text-muted-foreground marker:text-muted-foreground/60">
                {removedItems(data, single).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            {kept && <p className="text-pretty text-muted-foreground">{kept}</p>}
            {data.active_jobs > 0 && <p className="text-pretty text-muted-foreground">{data.active_jobs === 1 ? `1 background task for ${single ? 'this paper' : 'these papers'} stops.` : `${countFormat.format(data.active_jobs)} background tasks for ${single ? 'this paper' : 'these papers'} stop.`}</p>}
            {data.answering && (
              <Alert>
                <MessageSquareWarning aria-hidden="true" />
                <AlertDescription>{single ? 'A conversation about this paper is still writing an answer. Delete the paper when it finishes.' : 'A conversation about these papers is still writing an answer. Delete them when it finishes.'}</AlertDescription>
              </Alert>
            )}
          </div>
        )}
        <ErrorNotice error={remove.error} />
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={!data || data.answering || remove.isPending}
            onClick={(event) => {
              // The dialog stays open while deleting, so a failure is shown where it happened.
              event.preventDefault()
              remove.mutate(ids, {
                onSuccess: (deleted) => {
                  toast.success(single ? `Deleted “${name}”` : `Deleted ${countFormat.format(papers.length)} papers`)
                  onOpenChange(false)
                  onDeleted?.(deleted)
                },
              })
            }}
          >
            {remove.isPending ? 'Deleting…' : confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
