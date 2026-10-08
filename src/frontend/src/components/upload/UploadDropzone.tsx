import { useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Upload, X } from 'lucide-react'
import type { UploadAccepted } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { JobProgress } from '@/components/jobs/JobProgress'
import { cn } from '@/lib/utils'
import { useUploadPdf } from './use-upload'
import { validatePdf } from './validate-pdf'

function formatSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }

/**
 * Drop or choose one PDF, then confirm with Upload PDF. The file input stays in the DOM (visually hidden)
 * so keyboard, screen-reader and automation users get the native picker.
 */
export function UploadDropzone({ paperId, onAccepted, onSettled, title, description, className }: { paperId?: string; onAccepted?: (accepted: UploadAccepted) => void; onSettled?: () => void; title?: string; description?: string; className?: string }) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const upload = useUploadPdf(paperId)
  const problem = validatePdf(file)
  function choose(next: File | null) { upload.reset(); setFile(next) }
  if (upload.data) {
    const accepted = upload.data
    return (
      <div className={cn('grid gap-3 rounded-xl border bg-card p-4', className)}>
        <p role="status" className="text-sm font-medium">PDF uploaded. Processing continues in the background.</p>
        <JobProgress jobId={accepted.job_id} onSettled={onSettled} />
        <div className="flex flex-wrap gap-2">
          {!paperId && <Button asChild size="sm"><Link to={`/papers/${accepted.paper_id}`}>Open uploaded paper</Link></Button>}
          <Button size="sm" variant="ghost" onClick={() => { choose(null); if (input.current) input.current.value = '' }}>Upload another PDF</Button>
        </div>
      </div>
    )
  }
  return (
    <div className={cn('grid gap-3', className)}>
      <label
        htmlFor={`${id}-file`}
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files[0] ?? null) }}
        className={cn('flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-8 text-center transition-colors hover:bg-muted/50 has-focus-visible:ring-3 has-focus-visible:ring-ring/50', dragging && 'border-foreground/40 bg-muted')}
      >
        <span className="flex size-10 items-center justify-center rounded-full bg-muted"><Upload className="size-4" aria-hidden="true" /></span>
        <span className="text-sm font-medium">{title ?? 'Drop a PDF here, or choose one'}</span>
        <span className="max-w-xs text-xs text-muted-foreground">{description ?? 'Text-based PDF, up to 25 MB. The original stays available for reading and citations.'}</span>
        <input ref={input} id={`${id}-file`} aria-label="PDF file" type="file" accept="application/pdf,.pdf" className="sr-only" disabled={upload.isPending} onChange={(event) => choose(event.target.files?.[0] ?? null)} />
      </label>
      {file && (
        <div className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2">
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="min-w-0 flex-1"><p className="truncate text-sm">{file.name}</p><p className="tabular text-xs text-muted-foreground">{formatSize(file.size)}</p></div>
          <Button size="icon-sm" variant="ghost" aria-label="Remove file" disabled={upload.isPending} onClick={() => { choose(null); if (input.current) input.current.value = '' }}><X /></Button>
          <Button size="sm" disabled={!!problem || upload.isPending} onClick={() => upload.mutate(file, { onSuccess: onAccepted })}>{upload.isPending ? 'Uploading…' : 'Upload PDF'}</Button>
        </div>
      )}
      <ErrorNotice error={problem ? new Error(problem) : upload.error} />
    </div>
  )
}
