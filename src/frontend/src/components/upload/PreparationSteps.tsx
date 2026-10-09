import { Circle, CircleAlert, CircleCheck } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import type { PreparationStep, StepState } from './preparation'

const stateText: Record<StepState, string> = { done: 'Done', active: 'In progress', pending: 'Not started', failed: 'Failed' }

function StepIcon({ state }: { state: StepState }) {
  if (state === 'active') return <Spinner className="size-4 text-muted-foreground" aria-hidden="true" />
  if (state === 'done') return <CircleCheck className="size-4" aria-hidden="true" />
  if (state === 'failed') return <CircleAlert className="size-4 text-destructive" aria-hidden="true" />
  return <Circle className="size-4 text-muted-foreground/50" aria-hidden="true" />
}

/** One step list for a new PDF, in the same words wherever it appears. */
export function PreparationSteps({ steps, className }: { steps: PreparationStep[]; className?: string }) {
  // Screen readers hear each new step once, not every percentage of an upload.
  const current = steps.find((step) => step.state === 'active' || step.state === 'failed') ?? steps.at(-1)
  return (
    <>
      <div aria-live="polite" className="sr-only">{current && (current.state === 'failed' ? `${current.label} failed. ${current.detail ?? ''}` : current.state === 'done' ? 'Ready' : current.label)}</div>
      <ol aria-label="Preparation steps" className={cn('grid gap-3', className)}>
        {steps.map((step) => (
          <li key={step.key} aria-current={step.state === 'active' ? 'step' : undefined} className="grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-x-3 gap-y-1.5 text-sm">
            <span className="flex h-5 items-center"><StepIcon state={step.state} /></span>
            <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3">
              <span className={cn(step.state === 'pending' && 'text-muted-foreground', step.state === 'failed' && 'text-destructive')}>{step.label}<span className="sr-only">{`: ${stateText[step.state]}`}</span></span>
              {step.detail && <span className={cn('text-xs text-pretty text-muted-foreground', step.key === 'upload' && 'tabular')}>{step.detail}</span>}
            </span>
            {step.key === 'upload' && step.state === 'active' && <Progress value={Number.parseInt(step.detail ?? '0', 10)} aria-label="Upload progress" className="col-start-2" />}
          </li>
        ))}
      </ol>
    </>
  )
}
