import { useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Copy, Info, Trash2 } from 'lucide-react'
import { providerLabels, type Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DeletePapersDialog } from '@/features/library/DeletePapersDialog'
import { paperName } from '@/features/research/paper-format'
import { LookupNotice } from './LookupNotice'
import { MetadataSources } from './MetadataSources'
import { SearchIndexPanel } from './SearchIndexPanel'
import { useOptionalWorkspace } from './workspace-context'

const LABEL = 'Sources and search index'

/** Copies an identifier exactly; the button's name says whether it worked, as the answer's copy button does. */
function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState<'copied' | 'failed' | null>(null)
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied('copied')
    } catch {
      setCopied('failed')
    }
    window.setTimeout(() => setCopied(null), 2000)
  }
  const name = copied === 'copied' ? 'Copied' : copied === 'failed' ? 'Couldn’t copy. Select the text instead.' : `Copy ${label}`
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button type="button" variant="ghost" size="icon-xs" aria-label={name} onClick={() => void copy()} className="shrink-0 text-muted-foreground hover:text-foreground">
          {copied === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="left">{name}</TooltipContent>
    </Tooltip>
  )
}

function Identifiers({ paper, headingId }: { paper: Paper; headingId: string }) {
  const rows = [
    ...(paper.doi ? [{ key: 'doi', label: 'DOI', value: paper.doi }] : []),
    ...paper.sources.map((source) => ({ key: `${source.provider}:${source.external_id}`, label: `${providerLabels[source.provider]} ID`, value: source.external_id })),
  ]
  return (
    <section aria-labelledby={headingId} className="grid gap-2">
      <h3 id={headingId} className="text-sm font-medium">Identifiers</h3>
      {rows.length ? (
        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-center gap-x-6 gap-y-1 text-sm">
          {rows.map((row) => (
            <div key={row.key} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="flex min-w-0 items-center gap-1">
                <span className="min-w-0 flex-1 font-mono text-[0.8125rem] break-all">{row.value}</span>
                <CopyValue label={row.label} value={row.value} />
              </dd>
            </div>
          ))}
        </dl>
      ) : <p className="text-sm text-muted-foreground">No DOI or catalog record yet.</p>}
    </section>
  )
}

/**
 * ⓘ in the paper header (ARA-101): the details behind the bibliography, in a centred dialog. Where each field came
 * from, with Look up again; the catalog identifiers to copy; the paper's search index; and, for the workspace's own
 * paper, Delete paper. The bibliography itself is on the page, above the PDF.
 */
export function PaperSourcesDialog({ paper }: { paper: Paper }) {
  const id = useId()
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)
  // Another paper's tab (ARA-088) describes that paper, but deleting stays with the workspace's own.
  const own = useOptionalWorkspace()?.paper.id === paper.id
  return (
    <>
      <Dialog>
        <Tooltip>
          <TooltipTrigger asChild>
            <DialogTrigger asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label={LABEL} className="shrink-0 text-muted-foreground hover:text-foreground"><Info aria-hidden="true" /></Button>
            </DialogTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom">{LABEL}</TooltipContent>
        </Tooltip>
        <DialogContent className="max-h-[calc(100dvh-2rem)] gap-6 overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{LABEL}</DialogTitle>
            <DialogDescription className="break-words">{paperName(paper)}</DialogDescription>
          </DialogHeader>
          <MetadataSources provenance={paper.metadata_provenance} headingId={`${id}-sources`}>
            <LookupNotice paper={paper} />
          </MetadataSources>
          <Identifiers paper={paper} headingId={`${id}-identifiers`} />
          {paper.document_status === 'ready' && <SearchIndexPanel paperId={paper.id} />}
          {own && (
            <div className="grid justify-items-start gap-4">
              <Separator />
              <Button variant="destructive" size="sm" onClick={() => setDeleting(true)}><Trash2 data-icon="inline-start" aria-hidden="true" />Delete paper…</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
      {own && <DeletePapersDialog papers={[paper]} open={deleting} onOpenChange={setDeleting} onDeleted={() => navigate('/library', { replace: true })} />}
    </>
  )
}
