import { AlertCircle } from 'lucide-react'
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Inline, actionable error. Errors never go to toasts so screen readers get one alert in context. */
export function ErrorNotice({ error, retry, className }: { error: unknown; retry?: () => void; className?: string }) {
  if (!error) return null
  return (
    <Alert role="alert" variant="destructive" className={cn('items-center', className)}>
      <AlertCircle aria-hidden="true" />
      <AlertDescription>{error instanceof Error ? error.message : 'Something went wrong. Try again.'}</AlertDescription>
      {retry && <AlertAction><Button size="sm" variant="outline" onClick={retry}>Try again</Button></AlertAction>}
    </Alert>
  )
}
