import { safeUrl } from '@/api/client'
import { providerLabels, type Provider } from '@/api/types'

export type AuthorLine = { short: string; full: string; truncated: boolean }

/** Drops control and private-use characters that some provider records and PDF fonts leak into names and titles. */
export function displayText(value: string | null | undefined): string {
  return (value ?? '').replace(/[\p{Cc}\p{Co}]/gu, ' ').replace(/\s+/g, ' ').trim()
}

/** A paper's title, else its PDF's file name while the title is still being read (ARA-086). */
export function paperName(paper: { title: string | null; file_name?: string | null }): string {
  return displayText(paper.title) || displayText(paper.file_name) || 'Untitled paper'
}

/** First `max` authors, then "et al."; the full list stays available for a tooltip and screen readers. */
export function authorLine(authors: string[] | null | undefined, max = 3): AuthorLine | null {
  const names = (authors ?? []).map(displayText).filter(Boolean)
  if (!names.length) return null
  const full = names.join(', ')
  return names.length > max ? { short: `${names.slice(0, max).join(', ')} et\u00a0al.`, full, truncated: true } : { short: full, full, truncated: false }
}

/** Accepts a bare DOI or a doi.org URL and returns the bare DOI with its resolver link. */
export function doiLink(doi: string | null | undefined): { doi: string; href: string } | null {
  const bare = doi?.trim().replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '')
  const href = bare ? safeUrl(`https://doi.org/${bare}`) : undefined
  return bare && href ? { doi: bare, href } : null
}

const knownHosts: [string, string][] = [['semanticscholar.org', providerLabels.semantic_scholar], ['openalex.org', providerLabels.openalex], ['arxiv.org', 'arXiv']]

/** Names a provider's record link by where it goes, so readers know which site opens. */
export function recordLink(url: string | null | undefined, doiHref?: string): { href: string; label: string } | null {
  const href = safeUrl(url)
  if (!href || (doiHref && href.toLowerCase() === doiHref.toLowerCase())) return null
  const host = new URL(href).hostname.replace(/^www\./, '')
  const known = knownHosts.find(([domain]) => host === domain || host.endsWith(`.${domain}`))
  return { href, label: known?.[1] ?? host }
}

export const otherProvider = (provider: Provider): Provider => (provider === 'openalex' ? 'semantic_scholar' : 'openalex')

export const countFormat = new Intl.NumberFormat('en-US')
