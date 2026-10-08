import type { LucideIcon } from 'lucide-react'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'

/** An empty state names what is missing and offers the next action. */
export function EmptyState({ icon: Icon, title, children, action, className }: { icon?: LucideIcon; title: string; children?: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <Empty className={className}>
      <EmptyHeader>
        {Icon && <EmptyMedia variant="icon"><Icon aria-hidden="true" /></EmptyMedia>}
        <EmptyTitle role="heading" aria-level={2}>{title}</EmptyTitle>
        {children && <EmptyDescription>{children}</EmptyDescription>}
      </EmptyHeader>
      {action && <EmptyContent>{action}</EmptyContent>}
    </Empty>
  )
}
