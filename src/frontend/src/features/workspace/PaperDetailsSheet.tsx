import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Copy, ExternalLink, Info, Pencil, Trash2 } from 'lucide-react'
import { safeUrl } from '@/api/client'
import { providerLabels, type Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ClampedText } from '@/components/paper/ClampedText'
import { PaperCitation } from '@/components/paper/PaperCitation'
import { DeletePapersDialog } from '@/features/library/DeletePapersDialog'
import { doiLink, paperName } from '@/features/research/paper-format'
import { useIsMobile } from '@/hooks/use-mobile'
import { EditDetailsDialog } from './BibliographyEditor'
import { LookupNotice } from './LookupNotice'
import { MetadataSources } from './MetadataSources'
import { SearchIndexPanel } from './SearchIndexPanel'

const linkClass = 'inline-flex items-center gap-1 rounded-sm underline decoration-foreground/25 underline-offset-4 outline-none hover:decoration-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50'
const newTab = <span className="sr-only"> (opens in a new tab)</span>

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
      {paper.pdf_doi_owner && (
        <p className="text-sm text-pretty">
          {`This PDF’s DOI belongs to “${paper.pdf_doi_owner.title || 'Untitled paper'}” in your library.`}{' '}
          <Link to={`/papers/${paper.pdf_doi_owner.paper_id}`} className={linkClass}>Open that paper</Link>
        </p>
      )}
    </section>
  )
}

/** Where the paper lives outside the library: its DOI and the catalog records it was saved from. */
function Links({ paper }: { paper: Paper }) {
  const doi = doiLink(paper.doi)
  const links = [
    ...(doi ? [{ key: 'doi', label: 'DOI', href: doi.href }] : []),
    ...paper.sources.flatMap((source) => {
      const href = safeUrl(source.external_url)
      return href ? [{ key: `${source.provider}:${source.external_id}`, label: providerLabels[source.provider], href }] : []
    }),
  ]
  if (!links.length) return null
  return (
    <ul aria-label="Links" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {links.map((link) => (
        <li key={link.key}><a href={link.href} target="_blank" rel="noreferrer" className={linkClass}>{link.label}<ExternalLink aria-hidden="true" className="size-3.5 text-muted-foreground" />{newTab}</a></li>
      ))}
    </ul>
  )
}

/**
 * The paper's details behind ⓘ (ARA-097), where the Details tab used to be: citation and authors, the actions on its
 * details, the abstract, identifiers, where each field came from, the search index under Advanced, and Delete last.
 * It overlays the conversation from the right on desktop, so the PDF stays in view, and rises from the bottom on
 * narrow screens. Esc, the close button and a click outside close it, and focus returns to ⓘ.
 */
export function PaperDetailsSheet({ paper, onDeleted }: { paper: Paper; onDeleted: () => void }) {
  const id = useId()
  const isMobile = useIsMobile()
  const [dialog, setDialog] = useState<'edit' | 'delete' | null>(null)
  const authors = paper.authors.join(', ')
  return (
    <Sheet>
      <Tooltip>
        <TooltipTrigger asChild>
          <SheetTrigger asChild>
            <Button type="button" variant="ghost" size="icon-sm" aria-label="Paper details" className="shrink-0 text-muted-foreground hover:text-foreground"><Info aria-hidden="true" /></Button>
          </SheetTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">Paper details</TooltipContent>
      </Tooltip>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        // The PDF stays legible beside the sheet, so the desktop overlay only catches the click that closes it.
        overlayClassName={isMobile ? undefined : 'bg-transparent supports-backdrop-filter:backdrop-blur-none'}
        className="gap-0 data-[side=bottom]:h-[calc(100dvh-2rem)] data-[side=bottom]:rounded-t-xl data-[side=right]:w-full data-[side=right]:sm:max-w-[440px]"
      >
        <SheetHeader className="gap-1.5 border-b p-5 pr-12">
          <SheetTitle className="text-lg leading-snug font-semibold text-balance break-words">{paperName(paper)}</SheetTitle>
          <SheetDescription asChild><div><PaperCitation paper={paper} wrap className="text-sm" /></div></SheetDescription>
          {authors && <p className="text-sm text-pretty">{authors}</p>}
        </SheetHeader>
        <div className="grid min-h-0 flex-1 content-start gap-7 overflow-y-auto overscroll-contain p-5">
          <div className="grid gap-3">
            <LookupNotice paper={paper}>
              <Button variant="outline" size="sm" onClick={() => setDialog('edit')}><Pencil data-icon="inline-start" aria-hidden="true" />Edit details</Button>
            </LookupNotice>
            <Links paper={paper} />
          </div>
          <section aria-labelledby={`${id}-abstract`} className="grid gap-2">
            <h3 id={`${id}-abstract`} className="text-sm font-medium">Abstract</h3>
            {paper.abstract?.trim() ? <ClampedText text={paper.abstract.trim()} textClassName="max-w-[70ch] whitespace-pre-line" /> : <p className="text-sm text-muted-foreground">No abstract is available for this paper yet.</p>}
          </section>
          <Identifiers paper={paper} headingId={`${id}-identifiers`} />
          <MetadataSources provenance={paper.metadata_provenance} headingId={`${id}-sources`} />
          {paper.document_status === 'ready' && <SearchIndexPanel paperId={paper.id} />}
          <div className="grid justify-items-start gap-4">
            <Separator />
            <Button variant="destructive" size="sm" onClick={() => setDialog('delete')}><Trash2 data-icon="inline-start" aria-hidden="true" />Delete paper…</Button>
          </div>
        </div>
      </SheetContent>
      {dialog === 'edit' && <EditDetailsDialog paper={paper} onClose={() => setDialog(null)} />}
      <DeletePapersDialog papers={[paper]} open={dialog === 'delete'} onOpenChange={(open) => { if (!open) setDialog(null) }} onDeleted={onDeleted} />
    </Sheet>
  )
}
