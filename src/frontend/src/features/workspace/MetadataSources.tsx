const fields: Record<string, string> = { title: 'Title', authors: 'Authors', year: 'Year', venue: 'Venue', abstract: 'Abstract', doi: 'DOI' }
const sources: Record<string, string> = { manual: 'edited by you', openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', pdf: 'PDF metadata', pdf_metadata: 'PDF metadata', extraction: 'PDF text', llm: 'PDF text analysis' }

/** Where each bibliographic field came from, so corrected and extracted values can be told apart. */
export function MetadataSources({ provenance, headingId }: { provenance: Record<string, unknown>; headingId: string }) {
  const rows = Object.entries(fields).flatMap(([field, label]) => {
    const value = provenance[field]
    if (typeof value !== 'object' || value === null || !('source' in value) || typeof value.source !== 'string') return []
    return [`${label}: ${sources[value.source] ?? value.source.replaceAll('_', ' ')}`]
  })
  if (!rows.length) return null
  return (
    <section aria-labelledby={headingId} className="grid gap-2">
      <h3 id={headingId} className="text-sm font-medium">Metadata sources</h3>
      <ul className="grid gap-1 text-sm text-muted-foreground">{rows.map((row) => <li key={row}>{row}</li>)}</ul>
    </section>
  )
}
