import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
import { regionsFor, type PageGeometry, type Region } from './citation-region'
import { findEvidence } from './evidence'
import { FADE_MS, HOLD_MS } from './highlight-lifetime'
import type { HighlightOutcome, SourceRequest } from './workspace-context'

// The worker comes from the same pdfjs-dist that react-pdf resolves, so API and worker versions always agree.
// pdfjs-dist 6 has no isEvalSupported option: its PostScript functions are interpreted, never compiled with eval.
pdfjs.GlobalWorkerOptions.workerSrc = workerSrc
const GUTTER = 16
const DEFAULT_RATIO = 11 / 8.5
const DEVICE_PIXEL_RATIO = Math.min(2, window.devicePixelRatio || 1)
const HIGHLIGHT_TIMEOUT_MS = 8000
/** Time left to read a passage the pointer has just stopped covering during a fade. */
const MIN_RESUME_MS = 1000

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
  /** Shown above page 1 in the same scroll column, so it scrolls away with the document (the paper header, ARA-101). */
  header?: React.ReactNode
}

type ActiveHighlight = { citation: Citation; claim?: string; nonce: number; reported: boolean; waitingForGeometry?: boolean; expired?: boolean }
type LoadedDocument = Parameters<NonNullable<DocumentProps['onLoadSuccess']>>[0]

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
function offsetIn(root: HTMLElement, element: Element) { return element.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop }
/** Scrolls so the vertical middle of `element` is the middle of the reader. */
function centreIn(root: HTMLElement, element: Element) {
  const middle = offsetIn(root, element) + element.getBoundingClientRect().height / 2
  root.scrollTo({ top: Math.max(0, middle - root.clientHeight / 2), behavior: prefersReducedMotion() ? 'instant' : 'smooth' })
}

/**
 * Wraps characters [start, end) of a text-layer span in a <mark>, as pdf.js's own find highlighter does, so a passage
 * that begins mid-line is marked from its first character. Returns the span itself when the range is all of it or
 * the span is not one run of text, so that span is marked whole rather than not at all.
 */
function markRange(span: HTMLElement, start: number, end: number): HTMLElement {
  const run = span.firstChild
  if (span.childNodes.length !== 1 || !(run instanceof Text)) return span
  if ((start <= 0 && end >= run.length) || end <= start) return span
  const cited = start > 0 ? run.splitText(start) : run
  if (end - start < cited.length) cited.splitText(end - start)
  const mark = document.createElement('mark')
  cited.replaceWith(mark)
  mark.append(cited)
  return mark
}

/** Unwraps every mark and clears every mark attribute, so each jump starts from the text layer as pdf.js drew it. */
function clearMarks(root: HTMLElement) {
  root.querySelectorAll('mark[data-citation-highlight]').forEach((mark) => {
    const span = mark.parentElement
    mark.replaceWith(...mark.childNodes)
    span?.normalize()
  })
  root.querySelectorAll('[data-citation-highlight]').forEach((element) => {
    element.removeAttribute('data-citation-highlight')
    element.removeAttribute('data-citation-pulse')
  })
}

const NO_REGIONS: Region[] = []
const percent = (value: number) => `${Number(value.toFixed(3))}%`

const PdfPage = memo(function PdfPage({ pageNumber, width, height, render, regions, nonce, onTextLayer, onTextLayerError }: {
  pageNumber: number
  width: number
  height: number
  render: boolean
  regions: Region[]
  /** Changes with each jump, so an outline is redrawn (and pulses) even for the same boxes. */
  nonce: number
  onTextLayer: (page: number) => void
  onTextLayerError: (page: number) => void
}) {
  // Stable callbacks: a new identity would make react-pdf re-render the text layer and drop the highlight.
  const textRendered = useCallback(() => onTextLayer(pageNumber), [onTextLayer, pageNumber])
  const textFailed = useCallback(() => onTextLayerError(pageNumber), [onTextLayerError, pageNumber])
  return (
    <div data-pdf-page={pageNumber} role="group" aria-label={`Page ${pageNumber}`} className="pdf-page relative isolate shrink-0 overflow-hidden bg-card" style={{ width, height }}>
      {render && <Page pageNumber={pageNumber} width={width} devicePixelRatio={DEVICE_PIXEL_RATIO} loading={null} onRenderTextLayerSuccess={textRendered} onRenderTextLayerError={textFailed} />}
      {regions.map((region, index) => (
        <div
          key={`${nonce}-${index}`}
          data-citation-region=""
          data-citation-pulse=""
          aria-hidden="true"
          style={{ left: percent(region.left), top: percent(region.top), width: percent(region.width), height: percent(region.height) }}
        />
      ))}
    </div>
  )
})

/**
 * Every page in one scroll column. Pages are placeholders sized from the PDF until they come near the viewport,
 * so long papers stay light. A highlight request scrolls to its page and, once that page's text layer exists, marks
 * the characters of the sentences that support the claim data-citation-highlight="strong" (whole spans, or <mark>s
 * inside spans where a sentence starts or ends mid-line) and the excerpt's other spans "context"; without a claim
 * the whole excerpt is strong.
 */
export default function PdfViewer(props: PdfViewerProps) {
  const { documentId, zoom, navigation, highlight } = props
  const rootRef = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  const request = useRef<ActiveHighlight | null>(null)
  const pendingPage = useRef<number | null>(null)
  // Where the reader is, kept across zoom and width changes: a page and the fraction into it, or page 0 for the header
  // above page 1, with the distance from the top in pixels. It starts at the very top (ARA-101).
  const anchor = useRef({ page: 0, offset: 0 })
  const reportedPage = useRef(1)
  const frame = useRef(0)
  const life = useRef({ timer: 0, deadline: 0, remaining: HOLD_MS, phase: 'idle' as 'idle' | 'hold' | 'fade' | 'gone', overText: false, overRegion: false })
  const geometry = useRef<Map<number, PageGeometry> | null>(null)
  const [regions, setRegions] = useState<{ nonce: number; list: Region[] }>({ nonce: 0, list: [] })
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

  const stopLife = useCallback(() => {
    const state = life.current
    window.clearTimeout(state.timer)
    state.timer = 0
    state.phase = 'idle'
    rootRef.current?.removeAttribute('data-citation-fade')
  }, [])

  /** End of the fade: the same clean-up a new citation does, and the passage is not marked again by a redrawn layer. */
  const expire = useCallback(() => {
    const root = rootRef.current
    life.current.phase = 'gone'
    life.current.timer = 0
    if (request.current) request.current.expired = true
    if (!root) return
    root.removeAttribute('data-citation-fade')
    clearMarks(root)
    setRegions({ nonce: 0, list: [] })
  }, [])

  const beginFade = useCallback(() => {
    const root = rootRef.current
    if (!root || prefersReducedMotion()) { expire(); return }
    life.current.phase = 'fade'
    root.style.setProperty('--citation-fade-ms', `${FADE_MS}ms`)
    root.setAttribute('data-citation-fade', 'out')
    life.current.timer = window.setTimeout(expire, FADE_MS)
  }, [expire])

  const runHold = useCallback((ms: number) => {
    const state = life.current
    window.clearTimeout(state.timer)
    state.phase = 'hold'
    state.deadline = Date.now() + ms
    state.timer = window.setTimeout(beginFade, ms)
  }, [beginFade])

  /** Holding a passage while the pointer is over it, so a reader is not racing the fade. */
  const pauseLife = useCallback(() => {
    const state = life.current
    if (state.phase === 'hold') {
      state.remaining = Math.max(0, state.deadline - Date.now())
    } else if (state.phase === 'fade') {
      state.remaining = MIN_RESUME_MS
      state.phase = 'hold'
      rootRef.current?.removeAttribute('data-citation-fade')
    } else return
    window.clearTimeout(state.timer)
    state.timer = 0
  }, [])

  const resumeLife = useCallback(() => {
    const state = life.current
    if (state.phase === 'hold' && !state.timer) runHold(state.remaining)
  }, [runHold])

  const setHover = useCallback((kind: 'text' | 'region', over: boolean) => {
    const state = life.current
    const before = state.overText || state.overRegion
    if (kind === 'text') state.overText = over
    else state.overRegion = over
    const after = state.overText || state.overRegion
    if (after && !before) pauseLife()
    else if (!after && before) resumeLife()
  }, [pauseLife, resumeLife])

  const settle = useCallback((outcome: HighlightOutcome, nonce: number) => {
    const active = request.current
    if (!active || active.nonce !== nonce || active.reported) return
    active.reported = true
    latest.current.onHighlight(outcome)
    if (outcome === 'page-only') return
    life.current.remaining = HOLD_MS
    life.current.phase = 'hold'
    if (life.current.overText || life.current.overRegion) life.current.timer = 0
    else runHold(HOLD_MS)
  }, [runHold])

  /**
   * The excerpt is not in the text layer: outline the citation's stored layout boxes instead, or settle page-only when
   * there are none. Waits for the page geometry (fetched with the document) before deciding.
   */
  const outlineRegions = useCallback((nonce: number) => {
    const active = request.current
    if (!active || active.nonce !== nonce || active.reported) return
    if (!geometry.current) { active.waitingForGeometry = true; return }
    const list = regionsFor(active.citation, geometry.current)
    if (list.length) setRegions({ nonce, list })
    settle(list.length ? 'region' : 'page-only', nonce)
  }, [settle])

  /** Marks the cited passage on its page if that page's text layer is complete; the first time also reports and centres it. */
  const markPage = useCallback((pageNumber: number) => {
    const root = rootRef.current
    const active = request.current
    if (!root || !active || active.expired || active.citation.page !== pageNumber) return
    const layer = root.querySelector(`[data-pdf-page="${pageNumber}"] .textLayer`)
    // react-pdf appends .endOfContent when a text layer finishes; it is removed again when the layer re-renders.
    if (!layer?.querySelector('.endOfContent')) return
    const spans = Array.from(layer.querySelectorAll<HTMLElement>('span[role="presentation"]'))
    const items = spans.map((span) => ({ str: span.textContent ?? '', hasEOL: span.nextElementSibling?.tagName === 'BR' }))
    const { strong, context } = findEvidence(items, active.citation.excerpt, active.claim)
    clearMarks(root)
    const first = !active.reported
    if (first) void layer.getBoundingClientRect() // flush styles so marking the same passage again restarts the pulse
    for (const index of context) spans[index]?.setAttribute('data-citation-highlight', 'context')
    const marks = strong.flatMap(({ item, start, end }) => (spans[item] ? [markRange(spans[item], start, end)] : []))
    for (const element of marks) {
      element.setAttribute('data-citation-highlight', 'strong')
      if (first) element.setAttribute('data-citation-pulse', '')
    }
    if (!first) return
    if (marks.length) settle('highlighted', active.nonce)
    else outlineRegions(active.nonce)
    const start = marks[0]
    if (start) centreIn(root, start)
    // A chip in a now-hidden tab had focus; keep keyboard users in the document they were sent to.
    const focused = document.activeElement
    if (!(focused instanceof HTMLElement) || focused === document.body || !focused.offsetParent) root.focus({ preventScroll: true })
  }, [settle, outlineRegions])

  const onTextLayerError = useCallback((pageNumber: number) => {
    const active = request.current
    if (active?.citation.page === pageNumber) outlineRegions(active.nonce)
  }, [outlineRegions])

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
    const { page, offset } = anchor.current
    const element = root.querySelector<HTMLElement>(`[data-pdf-page="${page}"]`)
    // Above page 1 (the paper header) the spot is a distance from the top, which a new page size does not move.
    // Before this, a width change on load (a scrollbar appearing) jumped a fresh reader past the header to page 1.
    if (hadLayout && pendingPage.current === null) {
      if (page === 0) root.scrollTop = offset
      else if (element) root.scrollTop = offsetIn(root, element) + offset * element.offsetHeight
    }
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
    stopLife()
    life.current.overText = false
    life.current.overRegion = false
    if (rootRef.current) clearMarks(rootRef.current)
    request.current = { citation, claim, nonce, reported: false }
    pendingPage.current = citation.page
    flushPendingPage()
    markPage(citation.page)
    const timer = window.setTimeout(() => outlineRegions(nonce), HIGHLIGHT_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [highlight, flushPendingPage, markPage, outlineRegions, stopLife])

  useEffect(() => () => window.clearTimeout(life.current.timer), [])

  // Once the outline is on the page, bring it to the middle of the reader.
  useLayoutEffect(() => {
    const root = rootRef.current
    const outline = regions.list.length ? root?.querySelector('[data-citation-region]') : null
    if (root && outline) centreIn(root, outline)
  }, [regions])

  // Outlines belong to the jump that drew them: a newer request hides them at once, before anything is redrawn.
  const nonce = highlight?.nonce
  const byPage = useMemo(() => {
    const pages = new Map<number, Region[]>()
    for (const region of nonce === regions.nonce ? regions.list : []) pages.set(region.page, [...(pages.get(region.page) ?? []), region])
    return pages
  }, [regions, nonce])

  useEffect(() => () => window.cancelAnimationFrame(frame.current), [])

  function onPointerOver(event: React.PointerEvent) {
    if (event.target instanceof Element && event.target.closest('[data-citation-highlight]')) setHover('text', true)
  }

  function onPointerOut(event: React.PointerEvent) {
    if (!(event.target instanceof Element) || !event.target.closest('[data-citation-highlight]')) return
    const next = event.relatedTarget
    if (!(next instanceof Element) || !next.closest('[data-citation-highlight]')) setHover('text', false)
  }

  /** Outlines let the pointer through, so hovering one is a rectangle test. */
  function onPointerMove(event: React.PointerEvent) {
    const state = life.current
    if (state.phase === 'idle' || state.phase === 'gone') return
    const outlines = rootRef.current?.querySelectorAll('[data-citation-region]')
    if (!outlines?.length && !state.overRegion) return
    const over = Array.from(outlines ?? []).some((outline) => {
      const box = outline.getBoundingClientRect()
      return event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom
    })
    setHover('region', over)
  }

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
      const top = offsetIn(root, current)
      anchor.current = page === 1 && root.scrollTop < top
        ? { page: 0, offset: root.scrollTop }
        : { page, offset: (root.scrollTop - top) / Math.max(1, current.offsetHeight) }
      if (page !== reportedPage.current) { reportedPage.current = page; latest.current.onPageChange(page) }
    })
  }

  const onLoadSuccess = useCallback((pdf: LoadedDocument) => {
    setNumPages(pdf.numPages)
    latest.current.onDocumentLoad(pdf.numPages)
    void Promise.all(Array.from({ length: pdf.numPages }, (_, index) => pdf.getPage(index + 1).then((page) => {
      const viewport = page.getViewport({ scale: 1 })
      return { ratio: viewport.height / viewport.width, geometry: { view: page.view, viewport } as PageGeometry }
    }))).then((pages) => {
      setRatios(pages.map(({ ratio }) => ratio))
      geometry.current = new Map(pages.map(({ geometry }, index) => [index + 1, geometry]))
      const active = request.current
      if (active?.waitingForGeometry) { active.waitingForGeometry = false; outlineRegions(active.nonce) }
    }, () => {})
  }, [outlineRegions])

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
      onPointerOver={onPointerOver}
      onPointerOut={onPointerOut}
      onPointerMove={onPointerMove}
      // The viewer keeps its own place across size changes, so the browser's scroll anchoring would only fight it.
      className="pdf-viewer relative h-full overflow-auto bg-muted outline-none [overflow-anchor:none] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
    >
      {/* Pinned to the left edge, so a page zoomed wider than the reader does not carry it sideways. */}
      {props.header && <div className="sticky left-0 w-full">{props.header}</div>}
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
              regions={byPage.get(page) ?? NO_REGIONS}
              nonce={regions.nonce}
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
