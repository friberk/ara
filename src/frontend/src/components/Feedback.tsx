import { Button } from './ui/button'
export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  if (!error) return null
  return <div role="alert" className="error-notice"><p>{error instanceof Error ? error.message : 'Something went wrong. Try again.'}</p>{retry && <Button variant="outline" onClick={retry}>Try again</Button>}</div>
}
export function Loading({ children = 'Loading…' }: { children?: React.ReactNode }) { return <p role="status" className="muted loading">{children}</p> }
export function Empty({ title, children }: { title: string; children: React.ReactNode }) { return <div className="empty-state"><h2>{title}</h2><p>{children}</p></div> }
export function DocumentStatus({ state }: { state: string }) { const labels: Record<string, string> = { metadata_only: 'PDF needed', processing: 'Processing PDF', ready: 'Ready to read', failed: 'Processing failed' }; return <span className={`status status-${state}`}>{labels[state] ?? state}</span> }
