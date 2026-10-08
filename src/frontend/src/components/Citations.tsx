import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api, downloadUrl } from '../api/client'
import type { Citation } from '../api/types'
import { Button } from './ui/button'
import { ErrorNotice, Loading } from './Feedback'
function CitationButton({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  const source = useQuery({ queryKey: ['citation', citation.document_id, citation.chunk_id], queryFn: async () => { const source = await api<Citation>(`/documents/${encodeURIComponent(citation.document_id)}/chunks/${encodeURIComponent(citation.chunk_id)}`); if (source.document_id !== citation.document_id || source.chunk_id !== citation.chunk_id || source.page !== citation.page) throw new Error('This citation could not be matched to its source.'); return source }, enabled: open })
  return <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger asChild><Button size="sm" variant="outline">Page {citation.page}</Button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="source-dialog"><div className="list-heading"><Dialog.Title>Source · page {citation.page}</Dialog.Title><Dialog.Close asChild><Button size="icon" variant="ghost" aria-label="Close source"><X size={20}/></Button></Dialog.Close></div><Dialog.Description className="muted small">Physical page in the original PDF. Compare the excerpt with the answer.</Dialog.Description>{source.isPending && <Loading>Loading source excerpt…</Loading>}<ErrorNotice error={source.error} retry={() => void source.refetch()}/>{source.data && <blockquote className="source-excerpt">{source.data.excerpt}</blockquote>}<a href={downloadUrl(citation.document_id, citation.page)} target="_blank" rel="noreferrer">Open PDF at page {citation.page}</a></Dialog.Content></Dialog.Portal></Dialog.Root>
}
export function Citations({ citations, documentId }: { citations: Citation[]; documentId: string }) { const valid = citations.filter((citation) => citation.document_id === documentId); return <>{valid.length > 0 && <div className="citation-list" aria-label="Sources"><span className="small muted">Sources</span>{valid.map((citation, index) => <CitationButton key={`${citation.chunk_id}:${index}`} citation={citation}/>)}</div>}{valid.length !== citations.length && <p role="alert" className="error-text">A citation could not be matched to this document.</p>}</> }
