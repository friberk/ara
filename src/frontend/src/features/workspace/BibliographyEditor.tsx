import { useId } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { toast } from 'sonner'
import type { Paper, PaperPatch } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { usePatchPaper } from '@/hooks/queries/papers'

const schema = z.object({
  title: z.string().max(1000, 'Keep the title under 1,000 characters.'),
  authors: z.string().max(10000).refine((value) => value.split('\n').filter((author) => author.trim()).length <= 50, 'Use no more than 50 authors.'),
  year: z.string().refine((value) => !value || (/^\d{4}$/.test(value) && Number(value) >= 1500 && Number(value) <= 2100), 'Enter a publication year between 1500 and 2100.'),
  venue: z.string().max(300, 'Keep the venue under 300 characters.'),
  abstract: z.string().max(20000, 'Keep the abstract under 20,000 characters.'),
  doi: z.string().max(300, 'Keep the DOI under 300 characters.'),
})
type Values = z.infer<typeof schema>
const HINT = 'Fields you change here are kept when the paper is looked up again.'

/**
 * Corrects the paper's details, inline in Details or in a dialog from the Library (ARA-095).
 * Only changed fields are sent, so untouched fields keep their provider provenance.
 */
export function BibliographyEditor({ paper, onClose, variant = 'inline' }: { paper: Paper; onClose: () => void; variant?: 'inline' | 'dialog' }) {
  const id = useId()
  const save = usePatchPaper(paper.id)
  const { register, handleSubmit, formState: { errors, dirtyFields, isDirty } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { title: paper.title ?? '', authors: paper.authors.join('\n'), year: paper.year?.toString() ?? '', venue: paper.venue ?? '', abstract: paper.abstract ?? '', doi: paper.doi ?? '' },
  })
  function submit(values: Values) {
    const normalized = { title: values.title.trim() || null, authors: values.authors.split('\n').map((author) => author.trim()).filter(Boolean), year: values.year ? Number(values.year) : null, venue: values.venue.trim() || null, abstract: values.abstract.trim() || null, doi: values.doi.trim() || null }
    const patch: PaperPatch = {
      ...(dirtyFields.title ? { title: normalized.title } : {}),
      ...(dirtyFields.authors ? { authors: normalized.authors } : {}),
      ...(dirtyFields.year ? { year: normalized.year } : {}),
      ...(dirtyFields.venue ? { venue: normalized.venue } : {}),
      ...(dirtyFields.abstract ? { abstract: normalized.abstract } : {}),
      ...(dirtyFields.doi ? { doi: normalized.doi } : {}),
    }
    save.mutate(patch, { onSuccess: () => { toast.success('Details saved'); onClose() } })
  }
  const field = (name: keyof Values) => ({ id: `${id}-${name}`, 'aria-invalid': !!errors[name] || undefined, 'aria-describedby': errors[name] ? `${id}-${name}-error` : undefined, ...register(name) })
  const message = (name: keyof Values) => errors[name] && <p id={`${id}-${name}-error`} role="alert" className="text-sm text-destructive">{errors[name].message}</p>
  const submitButton = <Button type="submit" disabled={!isDirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save details'}</Button>

  return (
    <form className="grid gap-5" onSubmit={handleSubmit(submit)} aria-labelledby={variant === 'inline' ? `${id}-heading` : undefined} noValidate>
      {variant === 'dialog' ? (
        <DialogHeader>
          <DialogTitle>Edit details</DialogTitle>
          <DialogDescription>{HINT}</DialogDescription>
        </DialogHeader>
      ) : (
        <div className="grid gap-1">
          <h2 id={`${id}-heading`} className="text-base font-semibold">Edit details</h2>
          <p className="text-sm text-muted-foreground">{HINT}</p>
        </div>
      )}
      <div className="grid gap-2">
        <Label htmlFor={`${id}-title`}>Title</Label>
        <Input {...field('title')} />
        {message('title')}
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`${id}-authors`}>Authors</Label>
        <Textarea rows={3} {...field('authors')} aria-describedby={`${id}-authors-hint${errors.authors ? ` ${id}-authors-error` : ''}`} />
        <p id={`${id}-authors-hint`} className="text-xs text-muted-foreground">One author per line.</p>
        {message('authors')}
      </div>
      <div className="grid gap-4 sm:grid-cols-[8rem_1fr]">
        <div className="grid content-start gap-2">
          <Label htmlFor={`${id}-year`}>Publication year</Label>
          <Input inputMode="numeric" autoComplete="off" {...field('year')} />
        </div>
        <div className="grid content-start gap-2">
          <Label htmlFor={`${id}-doi`}>DOI</Label>
          <Input className="font-mono" autoComplete="off" spellCheck={false} {...field('doi')} />
        </div>
        <div className="sm:col-span-2">{message('year')}{message('doi')}</div>
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`${id}-venue`}>Venue</Label>
        <Input autoComplete="off" placeholder="Journal or conference" {...field('venue')} />
        {message('venue')}
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`${id}-abstract`}>Abstract</Label>
        <Textarea rows={6} className="max-h-80" {...field('abstract')} />
        {message('abstract')}
      </div>
      <ErrorNotice error={save.error} />
      {variant === 'dialog'
        ? <DialogFooter><Button type="button" variant="outline" onClick={onClose}>Cancel</Button>{submitButton}</DialogFooter>
        : <div className="flex flex-wrap gap-2">{submitButton}<Button type="button" variant="ghost" onClick={onClose}>Cancel</Button></div>}
    </form>
  )
}

/** The editor in a dialog, for the Library and the workspace header (ARA-095). */
export function EditDetailsDialog({ paper, onClose }: { paper: Paper; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <BibliographyEditor paper={paper} onClose={onClose} variant="dialog" />
      </DialogContent>
    </Dialog>
  )
}
