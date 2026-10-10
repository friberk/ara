import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleAlert, CircleCheck, X } from 'lucide-react'
import type { UploadAccepted } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'
import { usePaper } from '@/hooks/queries/papers'
import { cn } from '@/lib/utils'
import { MatchDecision } from './MatchDecision'
import { usePreparation } from './use-preparation'
import { UploadError } from './upload-request'
import type { useUploads, UploadItem } from './use-upload'
import { formatSize } from './validate-pdf'

function Row({ icon, file, status, children, action }: { icon: React.ReactNode; file: File; status: React.ReactNode; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-4 py-3">
      <span className="flex items-center">{icon}</span>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{file.name}</p>
        <div className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">{status}</div>
      </div>
      <div className="flex items-center gap-1">{action}</div>
      {children}
    </li>
  )
}

const open = (file: File, paperId: string) => <Button asChild size="sm" variant="ghost"><Link to={`/papers/${paperId}`} aria-label={`Open ${file.name}`}>Open</Link></Button>
const done = <CircleCheck className="size-4" aria-hidden="true" />

/**
 * An accepted upload follows its paper's steps; the current one is the row's status. An upload that is a library
 * paper says so: joined automatically, or with its own Replace/Attach or Cancel choice (ARA-086).
 */
function AcceptedRow({ item, accepted, onDiscarded }: { item: UploadItem; accepted: UploadAccepted; onDiscarded: () => void }) {
  const steps = usePreparation({ paperId: accepted.paper_id, jobId: accepted.job_id, uploaded: true })
  // The placeholder answers as the library paper once the upload has joined it.
  const paper = usePaper(accepted.paper_id).data
  const [joined, setJoined] = useState<{ note: string; paperId: string } | null>(null)
  if (accepted.duplicate) return <Row icon={done} file={item.file} status="Already in your library" action={open(item.file, accepted.paper_id)} />
  if (joined) return <Row icon={done} file={item.file} status={joined.note} action={open(item.file, joined.paperId)} />
  if (paper?.id && paper.id !== accepted.paper_id) return <Row icon={done} file={item.file} status={`Added to “${paper.title || 'Untitled paper'}”`} action={open(item.file, paper.id)} />
  if (paper?.upload_match) {
    const match = paper.upload_match
    return (
      <Row icon={<CircleAlert className="size-4 text-muted-foreground" aria-hidden="true" />} file={item.file} status={null}>
        <MatchDecision
          paper={{ ...paper, upload_match: match }}
          variant="row"
          className="col-start-2 col-end-4 -mt-1"
          onResolved={(decision, result) => {
            if (decision === 'discard' || !result) onDiscarded()
            else setJoined({ note: `${match.has_pdf ? 'Replaced the PDF on' : 'Added to'} “${match.title || 'Untitled paper'}”`, paperId: result.id })
          }}
        />
      </Row>
    )
  }
  // A readable paper is Ready; a lookup still running after that is a note, not a wait.
  const ready = steps.some((step) => step.key === 'ready' && step.state === 'done')
  const current = steps.find((step) => step.state === 'active' || step.state === 'failed')
  const icon = ready ? <CircleCheck className="size-4" aria-hidden="true" /> : current?.state === 'failed' ? <CircleAlert className="size-4 text-destructive" aria-hidden="true" /> : <Spinner className="size-4 text-muted-foreground" aria-hidden="true" />
  const status = ready ? <><span>Ready</span>{current && <span>{current.label}</span>}</>
    : current ? <><span className={cn(current.state === 'failed' && 'text-destructive')}>{current.label}</span>{current.detail && <span>{current.detail}</span>}</> : <span>Reading pages</span>
  return <Row icon={icon} file={item.file} action={open(item.file, accepted.paper_id)} status={status} />
}

/** One row per file: upload progress, then its processing stage, or a specific error with a way forward. */
export function UploadList({ uploads, className }: { uploads: ReturnType<typeof useUploads>; className?: string }) {
  const headingId = useId()
  if (!uploads.items.length) return null
  return (
    <section aria-labelledby={headingId} className={cn('rounded-xl border', className)}>
      <div className="flex min-h-11 items-center justify-between gap-3 border-b px-4 py-1.5">
        <h2 id={headingId} className="text-sm font-medium">Uploads</h2>
        {uploads.items.some((item) => item.state !== 'uploading') && <Button size="sm" variant="ghost" className="-mr-2 text-muted-foreground" onClick={uploads.clear}>Clear</Button>}
      </div>
      <ul aria-label="Uploads" className="divide-y">
        {uploads.items.map((item) => {
          if (item.state === 'accepted' && item.accepted) return <AcceptedRow key={item.id} item={item} accepted={item.accepted} onDiscarded={() => uploads.remove(item.id)} />
          if (item.state === 'uploading') {
            const percent = Math.round(item.progress * 100)
            return (
              <Row key={item.id} icon={<Spinner className="size-4 text-muted-foreground" aria-hidden="true" />} file={item.file} status={<><span>Uploading</span><span className="tabular">{percent}%</span><span className="tabular">{formatSize(item.file.size)}</span></>} action={<Button size="icon-sm" variant="ghost" aria-label={`Cancel ${item.file.name}`} onClick={() => uploads.remove(item.id)}><X /></Button>}>
                <Progress value={percent} aria-label={`${item.file.name} upload progress`} className="col-start-2 col-end-4" />
              </Row>
            )
          }
          const owner = item.error instanceof UploadError ? item.error.paperId : undefined
          return (
            <Row
              key={item.id}
              icon={<CircleAlert className="size-4 text-destructive" aria-hidden="true" />}
              file={item.file}
              status={<span role="alert" className="text-destructive">{item.error?.message ?? 'The upload failed.'}</span>}
              action={<>
                {owner && <Button asChild size="sm" variant="ghost"><Link to={`/papers/${owner}`}>Open that paper</Link></Button>}
                {!item.invalid && !owner && <Button size="sm" variant="ghost" onClick={() => uploads.retry(item)}>Try again</Button>}
                <Button size="icon-sm" variant="ghost" aria-label={`Remove ${item.file.name}`} onClick={() => uploads.remove(item.id)}><X /></Button>
              </>}
            />
          )
        })}
      </ul>
    </section>
  )
}
