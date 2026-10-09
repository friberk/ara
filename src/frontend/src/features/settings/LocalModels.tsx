import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Download, Pause, Play, RotateCcw, Trash2 } from 'lucide-react'
import type { Model, ModelInstallation } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useModelAction } from '@/hooks/queries/local-models'
import { unavailableReason } from '@/hooks/queries/models'
import { modelBytes } from '@/lib/format-bytes'

const labels: Record<ModelInstallation['state'], string> = { missing: 'Weights not downloaded', queued: 'Queued', downloading: 'Downloading', pausing: 'Pausing', paused: 'Paused', verifying: 'Preparing model', ready: 'Installed', deleting: 'Deleting', failed: 'Failed' }
const inProgress = new Set<ModelInstallation['state']>(['queued', 'downloading', 'pausing', 'verifying', 'deleting'])
// Chat models need no label; the others serve search rather than answers.
const kindLabels: Partial<Record<Model['kind'], string>> = { embedding: 'Search', reranker: 'Ranking' }

function LocalModelRow({ model, isDefault }: { model: Model & { installation: ModelInstallation }; isDefault: boolean }) {
  const operation = useModelAction()
  const [confirming, setConfirming] = useState(false)
  const installation = model.installation
  const busy = inProgress.has(installation.state)
  const preparing = installation.state === 'verifying' || (installation.operation === 'verify' && busy) || (installation.state === 'ready' && model.unavailable_code === 'LOCAL_MODEL_REVALIDATION_REQUIRED')
  const preparationStage = installation.state === 'verifying' ? 'Checking model readiness.' : 'Waiting to check model readiness automatically.'
  const preparationFailed = installation.state === 'failed' && installation.operation === 'verify'
  const downloadRequired = installation.state === 'missing' || (preparationFailed && !installation.weights_present)
  const retryLabel = installation.operation === 'delete' ? 'deletion' : preparationFailed ? 'preparation' : 'download'
  const progress = installation.total_bytes ? Math.min(99, Math.floor(100 * installation.completed_bytes / installation.total_bytes)) : null
  const label = preparing ? 'Preparing model' : preparationFailed ? 'Preparation failed' : labels[installation.state]
  const run = (kind: 'download' | 'pause' | 'resume' | 'retry') => {
    if (kind === 'download') operation.mutate({ kind, modelKey: model.key })
    else if (installation.job_id) operation.mutate({ kind, jobId: installation.job_id })
  }
  return (
    <li className="py-5 first:pt-0 last:pb-0">
      <section aria-label={`Manage ${model.display_name}`} className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-x-5 gap-y-3">
          <div className="grid min-w-0 flex-1 gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium">{model.display_name}</h3>
              {kindLabels[model.kind] && <Badge variant="outline" className="font-normal text-muted-foreground">{kindLabels[model.kind]}</Badge>}
              <Badge variant="secondary" className="font-normal">{label}</Badge>
            </div>
            <p className="font-mono text-xs break-all text-muted-foreground">{model.model_id}</p>
            <p className="text-xs text-muted-foreground">{installation.quantization} · {modelBytes(installation.download_bytes)} download{isDefault ? ' · Saved default' : ''}</p>
          </div>
          <div className="flex shrink-0 gap-2">
            {downloadRequired && <Button size="sm" variant="outline" disabled={operation.isPending} aria-label={`Download ${model.display_name}`} onClick={() => run('download')}><Download aria-hidden="true" />{operation.isPending ? 'Queuing…' : 'Download'}</Button>}
            {!preparing && (installation.state === 'queued' || installation.state === 'downloading') && <Button size="sm" variant="outline" disabled={operation.isPending || !installation.job_id} aria-label={`Pause ${model.display_name} download`} onClick={() => run('pause')}><Pause aria-hidden="true" />Pause</Button>}
            {installation.state === 'paused' && <Button size="sm" variant="outline" disabled={operation.isPending || !installation.job_id} aria-label={`Resume ${model.display_name} download`} onClick={() => run('resume')}><Play aria-hidden="true" />Resume</Button>}
            {installation.state === 'failed' && !downloadRequired && <Button size="sm" variant="outline" disabled={operation.isPending} aria-label={`Retry ${model.display_name} ${retryLabel}`} onClick={() => run(installation.job_id ? 'retry' : 'download')}><RotateCcw aria-hidden="true" />Retry {retryLabel}</Button>}
            {installation.weights_present && !busy && !preparing && installation.state !== 'paused' && (
              <AlertDialog open={confirming} onOpenChange={setConfirming}>
                <AlertDialogTrigger asChild><Button size="sm" variant="ghost" disabled={operation.isPending} aria-label={`Delete ${model.display_name} weights`}><Trash2 aria-hidden="true" />Delete weights</Button></AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete {model.display_name} weights?</AlertDialogTitle>
                    <AlertDialogDescription>Your conversations and summaries will stay saved. You can download the weights again. Shared model files may remain on disk.{isDefault && ' This model will remain your saved default. Generation will be blocked until you download it again or change the default.'}</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter><AlertDialogCancel>Keep weights</AlertDialogCancel><AlertDialogAction onClick={() => operation.mutate({ kind: 'delete', modelKey: model.key })}>Delete weights</AlertDialogAction></AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
        </div>
        <span role="status" className="sr-only">{model.display_name}: {label}{preparing && `. ${preparationStage}`}</span>
        {preparing && (
          <div className="grid gap-1 text-sm text-muted-foreground">
            <p>{preparationStage}</p>
            <p className="text-xs">Preparation continues in the background, even if you leave Settings.</p>
          </div>
        )}
        {!preparing && (busy || installation.state === 'paused') && (
          <div className="grid gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted-foreground">
              <span>{modelBytes(installation.completed_bytes)}{installation.total_bytes ? ` of ${modelBytes(installation.total_bytes)}` : ' · Size pending'}</span>
              <span>{installation.state === 'pausing' ? 'Waiting for transfer to stop' : progress !== null ? `${progress}%` : 'Downloading'}</span>
            </div>
            <Progress value={progress} aria-label={`${model.display_name} download progress`} />
          </div>
        )}
        {model.status === 'unavailable' && installation.weights_present && !busy && !preparing && installation.state !== 'failed' && <p role="alert" className="text-sm text-destructive">{unavailableReason(model)}</p>}
        {installation.error && !operation.error && <p role="alert" className="text-sm text-destructive">{installation.error.message}</p>}
        <ErrorNotice error={operation.error} />
      </section>
    </li>
  )
}

/** Server-backed installation controls, kept separate from generation defaults. */
export function LocalModels({ models, defaultModel }: { models: Model[]; defaultModel?: string }) {
  const { hash } = useLocation()
  const section = useRef<HTMLElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (hash === '#local-models') {
      heading.current?.focus({ preventScroll: true })
      section.current?.scrollIntoView({ block: 'start' })
    }
  }, [hash])
  const local = models.filter((model): model is Model & { installation: ModelInstallation } => !!model.installation)
  if (!local.length) return null
  return (
    <section ref={section} id="local-models" aria-labelledby="local-models-heading" className="grid scroll-mt-8 gap-6">
      <div className="grid gap-1">
        <h2 ref={heading} tabIndex={-1} id="local-models-heading" className="w-fit rounded-sm text-base font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">Local models</h2>
        <p className="text-sm text-pretty text-muted-foreground">Download weights to run a model on this server. Downloads continue in the background. You can leave this page and return later.</p>
      </div>
      <ul className="divide-y">{local.map((model) => <LocalModelRow key={model.key} model={model} isDefault={defaultModel === model.key} />)}</ul>
    </section>
  )
}
