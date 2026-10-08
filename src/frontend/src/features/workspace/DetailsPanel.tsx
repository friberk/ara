import { useId, useState } from 'react'
import { ExternalLink, Pencil } from 'lucide-react'
import { downloadUrl, safeUrl } from '@/api/client'
import { providerLabels, type Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
import { BibliographyEditor } from './BibliographyEditor'
import { MetadataSources } from './MetadataSources'

const pdfState: Record<Exclude<Paper['document_status'], 'ready'>, string> = {
  metadata_only: 'No PDF attached yet. Attach one to read, summarize and ask about this paper.',
  processing: 'The PDF is being processed.',
  failed: 'The last PDF couldn’t be processed.',
}

function doiUrl(doi: string | null) { return doi ? safeUrl(`https://doi.org/${doi.split('/').map(encodeURIComponent).join('/')}`) : undefined }

/** Bibliography, provenance and the attached PDF. Edit swaps the summary for the correction form in place. */
export function DetailsPanel({ paper, onOpenPdf }: { paper: Paper; onOpenPdf: () => void }) {
  const id = useId()
  const [editing, setEditing] = useState(false)
  // A replacement uploaded here keeps its progress on screen while the paper reports processing.
  const [replacing, setReplacing] = useState(false)
  const doi = doiUrl(paper.doi)
  const records = paper.sources.flatMap((source) => {
    const url = safeUrl(source.external_url)
    return url ? [{ key: `${source.provider}:${source.external_id}`, label: providerLabels[source.provider], url }] : []
  })
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid max-w-2xl gap-8 px-5 py-6">
        {editing ? <BibliographyEditor paper={paper} onClose={() => setEditing(false)} /> : (
          <section aria-labelledby={`${id}-title`} className="grid gap-5">
            <div className="grid gap-2">
              <div className="flex items-start justify-between gap-3">
                <h2 id={`${id}-title`} className="text-lg leading-snug font-semibold text-balance">{paper.title || 'Untitled paper'}</h2>
                <Button variant="ghost" size="sm" className="-mr-2 shrink-0 text-muted-foreground" onClick={() => setEditing(true)}><Pencil data-icon="inline-start" aria-hidden="true" />Edit</Button>
              </div>
              <p className="text-sm">{paper.authors.length ? paper.authors.join(', ') : <span className="text-muted-foreground">Authors not available</span>}</p>
            </div>
            <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Year</dt>
              <dd className="tabular">{paper.year ?? <span className="text-muted-foreground">Not available</span>}</dd>
              <dt className="text-muted-foreground">DOI</dt>
              <dd>{doi ? <a href={doi} target="_blank" rel="noreferrer" className="font-mono text-[0.8125rem] break-all underline decoration-foreground/25 hover:decoration-foreground">{paper.doi}</a> : <span className="text-muted-foreground">Not available</span>}</dd>
              {records.length > 0 && (
                <>
                  <dt className="text-muted-foreground">Records</dt>
                  <dd className="flex flex-wrap gap-x-4 gap-y-1">{records.map((record) => <a key={record.key} href={record.url} target="_blank" rel="noreferrer" className="underline decoration-foreground/25 hover:decoration-foreground">{record.label}</a>)}</dd>
                </>
              )}
            </dl>
            <section aria-labelledby={`${id}-abstract`} className="grid gap-2">
              <h3 id={`${id}-abstract`} className="text-sm font-medium">Abstract</h3>
              {paper.abstract ? <p className="max-w-[70ch] text-sm leading-relaxed whitespace-pre-line text-pretty">{paper.abstract}</p> : <p className="text-sm text-muted-foreground">No abstract is available for this paper yet.</p>}
            </section>
            <MetadataSources provenance={paper.metadata_provenance} headingId={`${id}-sources`} />
          </section>
        )}
        <Separator />
        <section aria-labelledby={`${id}-pdf`} className="grid gap-3">
          <div className="flex items-center justify-between gap-3">
            <h3 id={`${id}-pdf`} className="text-sm font-medium">PDF</h3>
            {paper.active_document_id && (
              <Button asChild variant="ghost" size="sm" className="-mr-2 text-muted-foreground">
                <a href={downloadUrl(paper.active_document_id)} target="_blank" rel="noreferrer"><ExternalLink data-icon="inline-start" aria-hidden="true" />Open original PDF</a>
              </Button>
            )}
          </div>
          {/* Attaching and recovering happen in the PDF view's gate; here a ready paper can take a new version. */}
          {paper.document_status === 'ready' || replacing ? (
            <UploadDropzone paperId={paper.id} title="Replace the PDF" description="A new upload becomes the version you read and ask about. Earlier answers keep citing the PDF they used." onAccepted={() => setReplacing(true)} />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">{pdfState[paper.document_status]}</p>
              <Button variant="outline" size="sm" onClick={onOpenPdf}>{paper.document_status === 'processing' ? 'Show progress' : 'Attach a PDF'}</Button>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
