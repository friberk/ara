import { useId } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import type { MatchDecision as Decision, Paper, UploadMatch } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useResolveMatch } from '@/hooks/queries/uploads'
import { cn } from '@/lib/utils'
import { attachedNote, matchTitle } from './match-copy'


/**
 * The choice for an upload that is a library paper: Replace (or Attach, when it has no PDF) makes it that paper's
 * PDF; Cancel discards the upload. In the workspace the result opens the paper or the library; a library row
 * passes onResolved to stay in place.
 */
export function MatchDecision({ paper, variant = 'card', onResolved, className }: { paper: Paper & { upload_match: UploadMatch }; variant?: 'card' | 'banner' | 'row'; onResolved?: (decision: Decision, result: Paper | null) => void; className?: string }) {
  const id = useId()
  const navigate = useNavigate()
  const resolve = useResolveMatch(paper.id)
  const match = paper.upload_match
  const decide = (decision: Decision) => resolve.mutate(decision, {
    onSuccess: (result) => {
      if (onResolved) { onResolved(decision, result); return }
      if (decision === 'discard') { toast('Upload discarded.'); navigate('/library'); return }
      toast(attachedNote(match))
      if (result) navigate(`/papers/${result.id}`)
    },
  })
  const question = match.has_pdf ? 'It already has a PDF. Replace it with this one?' : 'It has no PDF yet. Attach this one to it?'
  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" disabled={resolve.isPending} onClick={() => decide('attach')}>
        {resolve.isPending && resolve.variables === 'attach' && <Spinner data-icon="inline-start" aria-hidden="true" />}{match.has_pdf ? 'Replace PDF' : 'Attach PDF'}
      </Button>
      <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => decide('discard')}>Cancel</Button>
    </div>
  )
  if (variant === 'row') {
    return (
      <div className={cn('grid gap-2', className)}>
        <p className="text-xs text-muted-foreground">{`Matches ${matchTitle(match)}, which ${match.has_pdf ? 'already has a PDF' : 'has no PDF yet'}`}</p>
        {actions}
        <ErrorNotice error={resolve.error} />
      </div>
    )
  }
  if (variant === 'banner') {
    return (
      <section aria-labelledby={id} className={cn('flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t bg-muted/50 px-4 py-2.5', className)}>
        <h2 id={id} className="sr-only">Library match</h2>
        <div className="grid min-w-0 gap-0.5 text-sm">
          <p className="font-medium text-pretty">{`This PDF matches ${matchTitle(match)} in your library.`}</p>
          <p className="text-muted-foreground">{question}</p>
        </div>
        {actions}
        <ErrorNotice error={resolve.error} className="basis-full" />
      </section>
    )
  }
  return (
    <section aria-labelledby={id} className={cn('grid gap-4', className)}>
      <div className="grid gap-1.5">
        <h2 id={id} className="text-sm font-medium text-pretty">{`This PDF matches ${matchTitle(match)} in your library.`}</h2>
        <p className="text-sm text-muted-foreground">{question}</p>
      </div>
      {actions}
      <ErrorNotice error={resolve.error} />
    </section>
  )
}
