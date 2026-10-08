import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Document, Page, pdfjs, type DocumentProps } from 'react-pdf'
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import './pdf-viewer.css'
import { downloadUrl } from '@/api/client'
import type { Citation } from '@/api/types'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import type { PdfNavigation } from './pdf-controls'
import { PagesSkeleton } from './PagesSkeleton'
import { findEvidence } from './evidence'
import type { HighlightOutcome, SourceRequest } from './workspace-context'

// The worker comes from the same pdfjs-dist that react-pdf resolves, so API and worker versions always agree.
// pdfjs-dist 6 has no isEvalSupported option: its PostScript functions are interpreted, never compiled with eval.
pdfjs.GlobalWorkerOptions.workerSrc = workerSrc
const GUTTER = 16
const DEFAULT_RATIO = 11 / 8.5
const DEVICE_PIXEL_RATIO = Math.min(2, window.devicePixelRatio || 1)
const HIGHLIGHT_TIMEOUT_MS = 8000

export type PdfViewerProps = {
  documentId: string
  /** 1 fits the page to the panel width. */
  zoom: number
  navigation: PdfNavigation | null
  /** A citation in this document to scroll to and mark, with the claim it supports; a new nonce repeats the jump. */
  highlight: SourceRequest | null
  onDocumentLoad: (numPages: number) => void
  onPageChange: (page: number) => void
  onHighlight: (outcome: HighlightOutcome) => void
}

type ActiveHighlight = { citation: Citation; claim?: string; nonce: number; reported: boolean }
type LoadedDocument = Parameters<NonNullable<DocumentProps['onLoadSuccess']>>[0]

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
function offsetIn(root: HTMLElement, element: Element) { return element.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop }

const PdfPage = memo(function PdfPage({ pageNumber, width, height, render, onTextLayer, onTextLayerError }: {
  pageNumber: number
  width: number
  height: number
  render: boolean
  onTextLayer: (page: number) => void
  onTextLayerError: (page: number) => void
}) {
  // Stable callbacks: a new identity would make react-pdf re-render the text layer and drop the highlight.
  const textRendered = useCallback(() => onTextLayer(pageNumber), [onTextLayer, pageNumber])
  const textFailed = useCallback(() => onTextLayerError(pageNumber), [onTextLayerError, pageNumber])
  return (
    <div data-pdf-page={pageNumber} role="group" aria-label={`Page ${pageNumber}`} className="pdf-page relative isolate shrink-0 overflow-hidden bg-card" style={{ width, height }}>
      {render && <Page pageNumber={pageNumber} width={width} devicePixelRatio={DEVICE_PIXEL_RATIO} loading={null} onRenderTextLayerSuccess={textRendered} onRenderTextLayerError={textFailed} />}
    </div>
  )
})

/**
 * Every page in one scroll column. Pages are placeholders sized from the PDF until they come near the viewport,
 * so long papers stay light. A highlight request scrolls to its page and, once that page's text layer exists, marks
 * the spans of the sentences that support the claim data-citation-highlight="strong" and the rest of the excerpt
 * "context" (the whole excerpt is strong without a claim).
 */
export default function PdfViewer(props: PdfViewerProps) {
  const { documentId, zoom, navigation, highlight } = props
  const rootRef = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  const request = useRef<ActiveHighlight | null>(null)
  const pendingPage = useRef<number | null>(null)
  const anchor = useRef({ page: 1, offset: 0 })
  const reportedPage = useRef(1)
  const frame = useRef(0)
  const [width, setWidth] = useState(0)
  const [numPages, setNumPages] = useState(0)
  const [ratios, setRatios] = useState<number[]>([])
  const [nearby, setNearby] = useState<ReadonlySet<number>>(() => new Set())
  const pageWidth = width ? Math.max(160, Math.floor((width - GUTTER * 2) * zoom)) : 0
  const measured = pageWidth > 0

  useLayoutEffect(() => { latest.current = props })

  /** Scrolls to the pending page once its placeholder exists and the viewer is visible. */
  const flushPendingPage = useCallback(() => {
    const root = rootRef.current
    const page = pendingPage.current
    if (!root || page === null || !root.clientHeight) return
    const element = root.querySelector(`[data-pdf-page="${page}"]`)
    if (!element) return
    pendingPage.current = null
    root.scrollTo({ top: offsetIn(root, element) - GUTTER / 2, behavior: 'instant' })
  }, [])

  const settle = useCallback((outcome: HighlightOutcome, nonce: number) => {
    const active = request.current
    if (!active || active.nonce !== nonce || active.reported) return
    active.reported = true
    latest.current.onHighlight(outcome)
  }, [])

  /** Marks the cited passage on its page if that page's text layer is complete; the first time also reports and centres it. */
  const markPage = useCallback((pageNumber: number) => {
    const root = rootRef.current
    const active = request.current
    if (!root || !active || active.citation.page !== pageNumber) return
    const layer = root.querySelector(`[data-pdf-page="${pageNumber}"] .textLayer`)
    // react-pdf appends .endOfContent when a text layer finishes; it is removed again when the layer re-renders.
    if (!layer?.querySelector('.endOfContent')) return
    const spans = Array.from(layer.querySelectorAll<HTMLElement>('span[role="presentation"]'))
    const items = spans.map((span) => ({ str: span.textContent ?? '', hasEOL: span.nextElementSibling?.tagName === 'BR' }))
    const evidence = findEvidence(items, active.citation.excerpt, active.claim)
    const strong = evidence.strong.map((range) => range.item)
    const { context } = evidence
    root.querySelectorAll('[data-citation-highlight]').forEach((element) => {
      element.removeAttribute('data-citation-highlight')
      element.removeAttribute('data-citation-pulse')
    })
    const first = !active.reported
    if (first) void layer.getBoundingClientRect() // flush styles so marking the same passage again restarts the pulse
    for (const index of context) spans[index]?.setAttribute('data-citation-highlight', 'context')
    for (const index of strong) {
      spans[index]?.setAttribute('data-citation-highlight', 'strong')
      if (first) spans[index]?.setAttribute('data-citation-pulse', '')
    }
    if (!first) return
    settle(strong.length ? 'highlighted' : 'page-only', active.nonce)
    const start = strong.length ? spans[strong[0]!] : undefined
    if (start) {
      const middle = offsetIn(root, start) + start.getBoundingClientRect().height / 2
      root.scrollTo({ top: Math.max(0, middle - root.clientHeight / 2), behavior: prefersReducedMotion() ? 'instant' : 'smooth' })
    }
    // A chip in a now-hidden tab had focus; keep keyboard users in the document they were sent to.
    const focused = document.activeElement
    if (!(focused instanceof HTMLElement) || focused === document.body || !focused.offsetParent) root.focus({ preventScroll: true })
  }, [settle])

  const onTextLayerError = useCallback((pageNumber: number) => {
    const active = request.current
    if (active?.citation.page === pageNumber) settle('page-only', active.nonce)
  }, [settle])

  // Width: measured at once, then re-measured after the panel stops resizing so canvases are not redrawn per frame.
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    let first = true
    let timer = 0
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry?.contentRect.width ?? 0)
      if (!next) return // hidden behind another tab: keep the last layout
      window.clearTimeout(timer)
      if (first) { first = false; setWidth(next) } else timer = window.setTimeout(() => setWidth(next), 150)
      flushPendingPage()
    })
    observer.observe(root)
    return () => { observer.disconnect(); window.clearTimeout(timer) }
  }, [flushPendingPage])

  // Pages within a viewport of the visible area are rendered; the rest stay placeholders.
  useEffect(() => {
    const root = rootRef.current
    if (!root || !numPages || !measured) return
    const observer = new IntersectionObserver((entries) => {
      setNearby((current) => {
        const next = new Set(current)
        for (const entry of entries) {
          const page = Number((entry.target as HTMLElement).dataset.pdfPage)
          if (entry.isIntersecting) next.add(page)
          else next.delete(page)
        }
        return next
      })
    }, { root, rootMargin: '100% 0px' })
    root.querySelectorAll('[data-pdf-page]').forEach((element) => observer.observe(element))
    return () => observer.disconnect()
  }, [numPages, measured])

  // Keep the same spot in view when zoom or panel width changes the page size.
  const previousWidth = useRef(pageWidth)
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root || previousWidth.current === pageWidth) return
    const hadLayout = previousWidth.current > 0
    previousWidth.current = pageWidth
    const element = root.querySelector<HTMLElement>(`[data-pdf-page="${anchor.current.page}"]`)
    if (hadLayout && element && pendingPage.current === null) root.scrollTop = offsetIn(root, element) + anchor.current.offset * element.offsetHeight
    flushPendingPage()
  }, [pageWidth, flushPendingPage])

  useLayoutEffect(() => { flushPendingPage() }, [numPages, flushPendingPage])

  useEffect(() => {
    if (!navigation || navigation.documentId !== documentId) return
    pendingPage.current = navigation.page
    flushPendingPage()
  }, [navigation, documentId, flushPendingPage])

  useEffect(() => {
    if (!highlight) return
    const { citation, claim, nonce } = highlight
    request.current = { citation, claim, nonce, reported: false }
    pendingPage.current = citation.page
    flushPendingPage()
    markPage(citation.page)
    const timer = window.setTimeout(() => settle('page-only', nonce), HIGHLIGHT_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [highlight, flushPendingPage, markPage, settle])

  useEffect(() => () => window.cancelAnimationFrame(frame.current), [])

  function trackScroll() {
    window.cancelAnimationFrame(frame.current)
    frame.current = window.requestAnimationFrame(() => {
      const root = rootRef.current
      if (!root) return
      const probe = root.scrollTop + root.clientHeight * 0.3
      let current: HTMLElement | null = null
      for (const element of root.querySelectorAll<HTMLElement>('[data-pdf-page]')) {
        if (current && offsetIn(root, element) > probe) break
        current = element
      }
      if (!current) return
      const page = Number(current.dataset.pdfPage)
      anchor.current = { page, offset: (root.scrollTop - offsetIn(root, current)) / Math.max(1, current.offsetHeight) }
      if (page !== reportedPage.current) { reportedPage.current = page; latest.current.onPageChange(page) }
    })
  }

  const onLoadSuccess = useCallback((pdf: LoadedDocument) => {
    setNumPages(pdf.numPages)
    latest.current.onDocumentLoad(pdf.numPages)
    void Promise.all(Array.from({ length: pdf.numPages }, (_, index) => pdf.getPage(index + 1).then((page) => {
      const viewport = page.getViewport({ scale: 1 })
      return viewport.height / viewport.width
    }))).then(setRatios, () => {})
  }, [])

  const goToItem = useCallback(({ pageNumber }: { pageNumber: number }) => {
    pendingPage.current = pageNumber
    flushPendingPage()
  }, [flushPendingPage])

  const target = highlight?.citation.page
  return (
    <div
      ref={rootRef}
      role="region"
      aria-label="PDF document"
      tabIndex={0}
      onScroll={trackScroll}
      className="pdf-viewer relative h-full overflow-auto bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
    >
      <Document
        file={downloadUrl(documentId)}
        suspense={false}
        loading={<PagesSkeleton />}
        error={<div className="p-4"><ErrorNotice error={new Error('This PDF couldn’t be displayed here. Open the original PDF instead.')} /></div>}
        onLoadSuccess={onLoadSuccess}
        onItemClick={goToItem}
        externalLinkTarget="_blank"
        externalLinkRel="noopener noreferrer"
        className="mx-auto flex w-max min-w-full flex-col items-center gap-4 p-4"
      >
        {measured && Array.from({ length: numPages }, (_, index) => {
          const page = index + 1
          return (
            <PdfPage
              key={page}
              pageNumber={page}
              width={pageWidth}
              height={Math.round(pageWidth * (ratios[index] ?? ratios[0] ?? DEFAULT_RATIO))}
              render={nearby.has(page) || page === target || (nearby.size === 0 && page <= 2)}
              onTextLayer={markPage}
              onTextLayerError={onTextLayerError}
            />
          )
        })}
      </Document>
    </div>
  )
}
