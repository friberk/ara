import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Collection, Paper } from '../api/types'
import { Button } from '../components/ui/button'
import { DocumentStatus, Empty, ErrorNotice, Loading } from '../components/Feedback'
import { Upload } from '../components/Upload'
export default function LibraryPage() {
  const [q, setQ] = useState(''); const [filter, setFilter] = useState('')
  const papers = useInfiniteQuery({ queryKey: ['papers', filter], initialPageParam: 0, queryFn: ({ pageParam, signal }) => api<Collection<Paper>>(`/papers?${new URLSearchParams({ q: filter, limit: '20', offset: String(pageParam) })}`, { signal }), getNextPageParam: (page, _all, offset) => page.items.length === 20 ? offset + 20 : undefined })
  const items = papers.data?.pages.flatMap((page) => page.items) ?? []
  return <section><h1>Your library</h1><p className="lead">Saved papers and uploaded documents stay here between visits.</p><Upload/><form className="library-filter" onSubmit={(event) => { event.preventDefault(); setFilter(q.trim()) }}><div className="field"><label htmlFor="library-query">Find in your library</label><input id="library-query" type="search" maxLength={300} value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search saved titles"/></div><Button type="submit" variant="outline">Filter papers</Button></form>{papers.isPending && <Loading>Loading your library…</Loading>}<ErrorNotice error={papers.error} retry={() => void papers.refetch()}/>{papers.data && (!items.length ? <Empty title={filter ? 'No matching papers' : 'Your library is empty'}>{filter ? 'Try another title.' : <>Search for a paper or upload a PDF to begin. <Link to="/search">Search papers</Link></>}</Empty> : <div className="paper-list">{items.map((paper) => <article className="paper-row" key={paper.id}><div><h2><Link to={`/papers/${paper.id}`}>{paper.title || 'Untitled paper'}</Link></h2><p className="bibliography">{paper.authors.join(', ') || 'Authors unavailable'} · {paper.year ?? 'Year unavailable'}</p></div><DocumentStatus state={paper.document_status}/></article>)}</div>)}{papers.hasNextPage && <Button className="load-more" variant="outline" disabled={papers.isFetchingNextPage} onClick={() => void papers.fetchNextPage()}>{papers.isFetchingNextPage ? 'Loading…' : 'Load more papers'}</Button>}</section>
}
