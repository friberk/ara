import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../api/client'
import type { Paper, PaperPatch } from '../api/types'
import { Button } from './ui/button'
import { ErrorNotice } from './Feedback'
const schema = z.object({ title: z.string().max(1000), authors: z.string().max(10000).refine((value) => value.split('\n').filter((author) => author.trim()).length <= 50, 'Use no more than 50 authors.'), year: z.string().refine((value) => !value || /^\d{4}$/.test(value) && Number(value) >= 1500 && Number(value) <= 2100, 'Enter a publication year between 1500 and 2100.'), abstract: z.string().max(20000), doi: z.string().max(300) })
type Values = z.infer<typeof schema>
export function MetadataEditor({ paper, close }: { paper: Paper; close: () => void }) {
  const client = useQueryClient(); const { register, handleSubmit, formState: { errors, dirtyFields, isDirty } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { title: paper.title ?? '', authors: paper.authors.join('\n'), year: paper.year?.toString() ?? '', abstract: paper.abstract ?? '', doi: paper.doi ?? '' } })
  const save = useMutation({ mutationFn: (values: Values) => {
    const normalized = { title: values.title.trim() || null, authors: values.authors.split('\n').map((author) => author.trim()).filter(Boolean), year: values.year ? Number(values.year) : null, abstract: values.abstract.trim() || null, doi: values.doi.trim() || null }
    const patch: PaperPatch = { ...(dirtyFields.title ? { title: normalized.title } : {}), ...(dirtyFields.authors ? { authors: normalized.authors } : {}), ...(dirtyFields.year ? { year: normalized.year } : {}), ...(dirtyFields.abstract ? { abstract: normalized.abstract } : {}), ...(dirtyFields.doi ? { doi: normalized.doi } : {}) }
    return api<Paper>(`/papers/${paper.id}`, json('PATCH', patch))
  }, onSuccess: (updated) => { client.setQueryData(['paper', paper.id], updated); void client.invalidateQueries({ queryKey: ['papers'] }); close() } })
  return <form className="metadata-form" onSubmit={handleSubmit((values) => save.mutate(values))}><h2>Edit bibliography</h2><div className="field"><label htmlFor="edit-title">Title</label><input id="edit-title" {...register('title')}/></div><div className="field"><label htmlFor="edit-authors">Authors <span className="muted">(one per line)</span></label><textarea id="edit-authors" rows={3} {...register('authors')}/></div><div className="field"><label htmlFor="edit-year">Publication year</label><input id="edit-year" inputMode="numeric" {...register('year')} aria-invalid={!!errors.year}/>{errors.year && <p role="alert" className="error-text">{errors.year.message}</p>}</div><div className="field"><label htmlFor="edit-doi">DOI</label><input id="edit-doi" {...register('doi')}/></div><div className="field"><label htmlFor="edit-abstract">Abstract</label><textarea id="edit-abstract" rows={5} {...register('abstract')}/></div>{Object.entries(errors).filter(([field]) => field !== 'year').map(([field, error]) => <p key={field} role="alert" className="error-text">{error?.message}</p>)}<div className="button-row"><Button type="submit" disabled={save.isPending || !isDirty}>{save.isPending ? 'Saving…' : 'Save bibliography'}</Button><Button type="button" variant="ghost" onClick={close}>Cancel</Button></div><ErrorNotice error={save.error}/></form>
}
