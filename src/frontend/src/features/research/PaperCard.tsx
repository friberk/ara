import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BookmarkPlus, Check, ExternalLink, FileText, MessageSquareText } from 'lucide-react'
import { toast } from 'sonner'
import { safeUrl } from '@/api/client'
import { providerLabels, type SearchHit } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useSavePaper } from '@/hooks/queries/papers'
import { cn } from '@/lib/utils'
import { PaperByline } from './PaperByline'
import { displayText, doiLink, recordLink } from './paper-format'

/** Clamped to three lines; Show more appears only when the text actually overflows. */
function Abstract({ text }: { text: string }) {
  const id = useId()
  const ref = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element || expanded) return
    // ResizeObserver reports once on observe, then on every width change (sidebar, window, font load).
    const observer = new ResizeObserver(() => setOverflowing(element.scrollHeight > element.clientHeight + 1))
    observer.observe(element)
    return () => observer.disconnect()
  }, [expanded, text])
  return (
    <div className="mt-2.5">
      <p ref={ref} id={id} className={cn('text-sm leading-6 text-pretty text-foreground/80', !expanded && 'line-clamp-3')}>{text}</p>
      {(overflowing || expanded) && (
        <button type="button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded((open) => !open)} className="mt-1 rounded-sm text-sm font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}

const newTab = <span className="sr-only"> (opens in a new tab)</span>
const linkClass = 'inline-flex items-center gap-1.5 rounded-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline'

function PaperLinks({ hit }: { hit: SearchHit }) {
  const doi = doiLink(hit.doi)
  const record = recordLink(hit.external_url, doi?.href)
  const pdf = safeUrl(hit.pdf_url)
  if (!doi && !record && !pdf) return null
  return (
    <ul className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
      {doi && (
        <li className="min-w-0">
          <a href={doi.href} target="_blank" rel="noreferrer" className={linkClass}>
            <span>DOI</span>
            <span className="font-mono text-xs break-all">{doi.doi}</span>
            {newTab}
          </a>
        </li>
      )}
      {record && (
        <li>
          <a href={record.href} target="_blank" rel="noreferrer" className={linkClass}>
            <ExternalLink className="size-3.5" aria-hidden="true" />{record.label}{newTab}
          </a>
        </li>
      )}
      {pdf && (
        <li>
          <a href={pdf} target="_blank" rel="noreferrer" className={linkClass}>
            <FileText className="size-3.5" aria-hidden="true" />PDF{newTab}
          </a>
        </li>
      )}
    </ul>
  )
}

/** One search result. Saving re-fetches the canonical record on the server; nothing from the browser is trusted. */
export function PaperCard({ hit }: { hit: SearchHit }) {
  const titleId = useId()
  const navigate = useNavigate()
  const save = useSavePaper()
  const savedId = save.data?.id ?? hit.saved_paper_id ?? null
  const title = displayText(hit.title) || 'Untitled paper'
  function saveThen(next?: (paperId: string) => void) {
    save.mutate({ provider: hit.provider, external_id: hit.external_id }, { onSuccess: (paper) => { toast.success('Saved to library'); next?.(paper.id) } })
  }
  function ask() {
    if (savedId) navigate(`/papers/${savedId}`)
    else saveThen((paperId) => navigate(`/papers/${paperId}`))
  }
  return (
    <article aria-labelledby={titleId} className="py-6">
      <h2 id={titleId} className="text-[17px] leading-snug font-semibold tracking-tight text-balance break-words">
        {savedId ? <Link to={`/papers/${savedId}`} className="rounded-sm underline-offset-4 hover:underline">{title}</Link> : title}
      </h2>
      <PaperByline authors={hit.authors} year={hit.year} className="mt-1.5" />
      {(hit.is_open_access === true || hit.locations?.some((location) => location.is_oa === true)) && <p className="mt-1.5 text-xs text-muted-foreground">Open copy reported</p>}
      {hit.abstract?.trim() ? <Abstract text={hit.abstract.trim()} /> : <p className="mt-2.5 text-sm text-muted-foreground">{providerLabels[hit.provider]} has no abstract for this paper.</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <PaperLinks hit={hit} />
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
          {savedId ? (
            <>
              <span className="inline-flex items-center gap-1.5 px-1 text-sm text-muted-foreground"><Check className="size-4" aria-hidden="true" />In library</span>
              <Button asChild variant="outline" size="sm"><Link to={`/papers/${savedId}`}>Open paper</Link></Button>
            </>
          ) : (
            <Button variant="outline" size="sm" disabled={save.isPending} onClick={() => saveThen()}>
              <BookmarkPlus aria-hidden="true" />{save.isPending ? 'Saving…' : 'Save to library'}
            </Button>
          )}
          <Button variant="ghost" size="sm" disabled={save.isPending} onClick={ask}>
            <MessageSquareText aria-hidden="true" />Ask about this paper
          </Button>
        </div>
      </div>
      <ErrorNotice error={save.error} className="mt-3" />
    </article>
  )
}
