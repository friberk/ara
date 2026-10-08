import { useId, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Upload as UploadIcon } from 'lucide-react'
import { api } from '../api/client'
import type { UploadAccepted } from '../api/types'
import { Button } from './ui/button'
import { ErrorNotice } from './Feedback'
import { JobProgress } from './JobProgress'
export function Upload({ paperId }: { paperId?: string }) {
  const id = useId(); const [file, setFile] = useState<File | null>(null); const [validation, setValidation] = useState<string | null>(null); const client = useQueryClient()
  const mutation = useMutation({ mutationFn: async () => { if (!file) throw new Error('Choose a PDF file.'); const body = new FormData(); body.append('file', file); body.append('request_id', crypto.randomUUID()); if (paperId) body.append('paper_id', paperId); return api<UploadAccepted>('/documents', { method: 'POST', body }) }, onSuccess: () => { void client.invalidateQueries({ queryKey: ['papers'] }); if (paperId) void client.invalidateQueries({ queryKey: ['paper', paperId] }) } })
  return <section className="upload-panel" aria-labelledby={`${id}-heading`}><h2 id={`${id}-heading`}>{paperId ? 'Attach a PDF' : 'Upload a paper'}</h2><p className="muted small">Choose a text-based PDF, up to 25 MB. Your original is retained for reading and citations.</p><form onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><div className="field"><label htmlFor={`${id}-file`}>PDF file</label><input id={`${id}-file`} type="file" accept="application/pdf,.pdf" disabled={mutation.isPending} onChange={(event) => { const chosen = event.target.files?.[0] ?? null; mutation.reset(); setValidation(chosen && chosen.size > 25 * 1024 * 1024 ? 'This PDF exceeds 25 MB. Choose a smaller file.' : chosen && !(chosen.type === 'application/pdf' || chosen.name.toLowerCase().endsWith('.pdf')) ? 'Choose a PDF file.' : null); setFile(chosen) }}/></div><Button type="submit" disabled={!file || !!validation || mutation.isPending}><UploadIcon size={16} aria-hidden="true"/>{mutation.isPending ? 'Uploading…' : 'Upload PDF'}</Button></form><ErrorNotice error={validation ? new Error(validation) : mutation.error}/>{mutation.data && <div className="upload-accepted"><p role="status">PDF uploaded. Processing continues in the background.</p><Link to={`/papers/${mutation.data.paper_id}`}>Open uploaded paper</Link><JobProgress jobId={mutation.data.job_id} onSettled={() => { void client.invalidateQueries({ queryKey: ['papers'] }); void client.invalidateQueries({ queryKey: ['paper', mutation.data.paper_id] }) }}/></div>}</section>
}
