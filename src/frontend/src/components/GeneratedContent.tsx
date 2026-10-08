import Markdown from 'react-markdown'
import { safeUrl } from '../api/client'
const sourceMarker = /\[source:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\]/g

export function GeneratedContent({ content }: { content: string }) {
  // Source controls use validated citations; keep these transport markers out of prose.
  const displayedContent = content.replace(sourceMarker, '')
  return <div className="generated-content rendered-markdown"><Markdown skipHtml components={{ a: ({ href, children }) => { const url = safeUrl(href ?? null); return url ? <a href={url} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span> }, img: () => null, h1: ({ children }) => <h3>{children}</h3>, h2: ({ children }) => <h3>{children}</h3>, h3: ({ children }) => <h4>{children}</h4> }}>{displayedContent}</Markdown></div>
}
