import { useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, FileText, Upload, X } from 'lucide-react'
import type { UploadAccepted } from '@/api/types'
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { PreparationSteps } from './PreparationSteps'
import { usePreparation } from './use-preparation'
import { preparationSteps } from './preparation'
import { UploadError } from './upload-request'
import { useUploads, type UploadItem } from './use-upload'
import { formatSize } from './validate-pdf'

export function UploadFailure({ item, onRetry, className }: { item: UploadItem; onRetry: () => void; className?: string }) {
  const owner = item.error instanceof UploadError ? item.error.paperId : undefined
  return (
    <Alert role="alert" variant="destructive" className={cn('items-center', className)}>
      <AlertCircle aria-hidden="true" />
      <AlertDescription>
        <span className="block">{item.error?.message ?? 'The upload failed. Try again.'}</span>
        {owner && <Link to={`/papers/${owner}`}>Open that paper</Link>}
      </AlertDescription>
      {!item.invalid && !owner && <AlertAction><Button size="sm" variant="outline" onClick={onRetry}>Try again</Button></AlertAction>}
    </Alert>
  )
}

function FileRow({ file, action }: { file: File; action?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{file.name}</p><p className="tabular text-xs text-muted-foreground">{formatSize(file.size)}</p></div>
      {action}
    </div>
  )
}

/** After acceptance: the same steps, now following the processing job. */
function Accepted({ item, paperId, onSettled, onReplace }: { item: UploadItem & { accepted: UploadAccepted }; paperId?: string; onSettled?: () => void; onReplace: () => void }) {
  const steps = usePreparation({ paperId: item.accepted.paper_id, jobId: item.accepted.job_id, uploaded: true, onSettled })
  return (
    <div className="grid gap-4 rounded-xl border bg-card p-4">
      <FileRow file={item.file} action={<Button size="sm" variant="ghost" className="text-muted-foreground" onClick={onReplace}>Upload a different PDF</Button>} />
      {item.accepted.duplicate && <p role="status" className="text-sm text-muted-foreground">{paperId ? 'This PDF is already attached to this paper.' : 'This PDF is already in your library.'}</p>}
      <PreparationSteps steps={steps} />
    </div>
  )
}

/**
 * Drop or choose one PDF and it uploads at once, with live progress, then the same steps follow its processing.
 * The file input stays in the DOM (visually hidden), so keyboard, screen-reader and automation users get the native
 * picker. A failed upload keeps the zone ready and offers a retry of the same request.
 */
export function UploadDropzone({ paperId, onAccepted, onSettled, title, description, className, chooseLabel, variant = 'zone' }: { paperId?: string; onAccepted?: (accepted: UploadAccepted) => void; onSettled?: () => void; title?: string; description?: string; className?: string; chooseLabel?: string; variant?: 'zone' | 'secondary' }) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const uploads = useUploads({ paperId, onAccepted: (accepted) => onAccepted?.(accepted) })
  const item = uploads.items.at(-1)
  function choose(files: FileList | File[] | null | undefined) {
    const file = files?.[0]
    if (input.current) input.current.value = ''
    if (!file) return
    for (const previous of uploads.items) uploads.remove(previous.id)
    uploads.add([file])
  }
  const reset = () => { for (const previous of uploads.items) uploads.remove(previous.id) }

  if (item?.state === 'accepted' && item.accepted) return <div className={className}><Accepted item={{ ...item, accepted: item.accepted }} paperId={paperId} onSettled={onSettled} onReplace={reset} /></div>
  if (item?.state === 'uploading') {
    return (
      <div className={cn('grid gap-4 rounded-xl border bg-card p-4', className)}>
        <FileRow file={item.file} action={<Button size="icon-sm" variant="ghost" aria-label="Cancel upload" onClick={reset}><X /></Button>} />
        <PreparationSteps steps={preparationSteps({ upload: { progress: item.progress }, documentStatus: 'metadata_only' })} />
      </div>
    )
  }
  if (variant === 'secondary') {
    // A quiet alternative while the PDF is on its way: the picker without the drop area.
    return (
      <div className={cn('grid justify-items-start gap-3', className)}>
        <input ref={input} aria-label="PDF file" type="file" accept="application/pdf,.pdf" tabIndex={-1} className="sr-only" onChange={(event) => choose(event.target.files)} />
        <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" onClick={() => input.current?.click()}>{chooseLabel ?? 'Upload your own copy instead'}</Button>
        {item?.state === 'failed' && <UploadFailure item={item} onRetry={() => uploads.retry(item)} />}
      </div>
    )
  }
  return (
    <div className={cn('grid gap-3', className)}>
      <label
        htmlFor={`${id}-file`}
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files) }}
        className={cn('flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-8 text-center transition-colors hover:bg-muted/50 has-focus-visible:ring-3 has-focus-visible:ring-ring/50', dragging && 'border-foreground/40 bg-muted')}
      >
        <span className="flex size-10 items-center justify-center rounded-full bg-muted"><Upload className="size-4" aria-hidden="true" /></span>
        <span className="text-sm font-medium">{title ?? 'Drop a PDF here, or choose one'}</span>
        <span className="max-w-xs text-xs text-muted-foreground">{description ?? 'Text-based PDF, up to 25 MB. The original stays available for reading and citations.'}</span>
        <input ref={input} id={`${id}-file`} aria-label="PDF file" type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(event) => choose(event.target.files)} />
      </label>
      {chooseLabel && <Button variant="outline" size="sm" className="justify-self-start" onClick={() => input.current?.click()}>{chooseLabel}</Button>}
      {item?.state === 'failed' && <UploadFailure item={item} onRetry={() => uploads.retry(item)} />}
    </div>
  )
}
