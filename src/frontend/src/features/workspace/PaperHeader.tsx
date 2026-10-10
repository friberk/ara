import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, Pencil } from 'lucide-react'
import { safeUrl } from '@/api/client'
import { providerLabels, type Paper } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ClampedText } from '@/components/paper/ClampedText'
import { PaperCitation } from '@/components/paper/PaperCitation'
import { doiLink, paperName } from '@/features/research/paper-format'
import { EditDetailsDialog } from './BibliographyEditor'
import { PaperSourcesDialog } from './PaperSourcesDialog'

const linkClass = 'inline-flex items-center gap-1 rounded-sm underline decoration-foreground/25 underline-offset-4 outline-none hover:decoration-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50'
const newTab = <span className="sr-only"> (opens in a new tab)</span>

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
 * The paper's bibliography at the top of the reader (ARA-101): title, every author, year and venue, its DOI and
 * catalog links, and the abstract clamped to three lines, with Edit details and ⓘ beside the title. Above a PDF it is
 * the first thing in the PDF's scroll column, so it scrolls away with page 1; above the ways to get a PDF it leads them.
 * Fields the paper lacks are left out, except the abstract, which says so.
 */
export function PaperHeader({ paper }: { paper: Paper }) {
  const id = useId()
  const [editing, setEditing] = useState(false)
  const authors = paper.authors.join(', ')
  return (
    <header aria-labelledby={`${id}-title`} className="border-b bg-background">
      {/* A container, so a narrow reader (a phone, or a 30% panel) gives the title the room, not the button labels. */}
      <div className="@container mx-auto grid max-w-3xl gap-3 px-5 pt-5 pb-6">
        <div className="flex items-start gap-3">
          <h2 id={`${id}-title`} className="min-w-0 flex-1 text-lg leading-snug font-semibold text-balance break-words">{paperName(paper)}</h2>
          <div className="-mt-0.5 -mr-2 flex shrink-0 items-center gap-0.5">
            <Button variant="ghost" size="sm" className="text-muted-foreground @max-md:pr-1.5" onClick={() => setEditing(true)}><Pencil data-icon="inline-start" aria-hidden="true" /><span className="sr-only @md:not-sr-only">Edit details</span></Button>
            <PaperSourcesDialog paper={paper} />
          </div>
        </div>
        {(authors || paper.year || paper.venue) && (
          <div className="grid gap-1">
            {authors && <p className="text-sm text-pretty">{authors}</p>}
            {(paper.year || paper.venue) && <p><PaperCitation paper={{ authors: [], year: paper.year, venue: paper.venue }} wrap className="text-sm" /></p>}
          </div>
        )}
        <Links paper={paper} />
        <div className="mt-1 grid gap-1.5">
          <h3 className="text-sm font-medium">Abstract</h3>
          {paper.abstract?.trim()
            ? <ClampedText text={paper.abstract.trim()} textClassName="max-w-[70ch] whitespace-pre-line" />
            : <p className="text-sm text-muted-foreground">No abstract is available for this paper yet.</p>}
        </div>
        {paper.pdf_doi_owner && (
          <p className="text-sm text-pretty">
            {`This PDF’s DOI belongs to “${paper.pdf_doi_owner.title || 'Untitled paper'}” in your library.`}{' '}
            <Link to={`/papers/${paper.pdf_doi_owner.paper_id}`} className={linkClass}>Open that paper</Link>
          </p>
        )}
      </div>
      {editing && <EditDetailsDialog paper={paper} onClose={() => setEditing(false)} />}
    </header>
  )
}
