import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

export function LoadingState({ children = 'Loading…', className }: { children?: React.ReactNode; className?: string }) {
  return <p role="status" className={cn('flex items-center gap-2 py-6 text-sm text-muted-foreground', className)}><Spinner aria-hidden="true" />{children}</p>
}
