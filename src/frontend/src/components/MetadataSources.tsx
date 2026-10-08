const fields: Record<string, string> = { title: 'Title', authors: 'Authors', year: 'Year', abstract: 'Abstract', doi: 'DOI' }
const sources: Record<string, string> = { manual: 'edited by you', openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', pdf: 'PDF metadata', pdf_metadata: 'PDF metadata', extraction: 'PDF text', llm: 'PDF text analysis' }
export function MetadataSources({ provenance }: { provenance: Record<string, unknown> }) {
  const rows = Object.entries(provenance).flatMap(([field, value]) => { if (!fields[field] || typeof value !== 'object' || value === null || !('source' in value) || typeof value.source !== 'string') return []; return [`${fields[field]}: ${sources[value.source] ?? value.source.replaceAll('_', ' ')}`] })
  return rows.length ? <details><summary>Metadata sources</summary><ul className="provenance-list">{rows.map((row) => <li key={row}>{row}</li>)}</ul></details> : null
}
