const fields: Record<string, string> = { title: 'Title', authors: 'Authors', year: 'Year', venue: 'Venue', abstract: 'Abstract', doi: 'DOI' }
const sources: Record<string, string> = { manual: 'Edited by you', openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', pdf: 'PDF metadata', pdf_metadata: 'PDF metadata', extraction: 'PDF text', llm: 'PDF text analysis' }

/** Where each bibliographic field came from, as a compact field → source list, so edits and extractions can be told apart. */
export function MetadataSources({ provenance, headingId }: { provenance: Record<string, unknown>; headingId: string }) {
  const rows = Object.entries(fields).flatMap(([field, label]) => {
    const value = provenance[field]
    if (typeof value !== 'object' || value === null || !('source' in value) || typeof value.source !== 'string') return []
    const source = sources[value.source] ?? value.source.replaceAll('_', ' ')
    return [{ field, label, source: source.charAt(0).toUpperCase() + source.slice(1) }]
  })
  if (!rows.length) return null
  return (
    <section aria-labelledby={headingId} className="grid gap-2">
      <h3 id={headingId} className="text-sm font-medium">Where this information came from</h3>
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-6 gap-y-1 text-sm">
        {rows.map((row) => (
          <div key={row.field} className="contents">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd>{row.source}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
