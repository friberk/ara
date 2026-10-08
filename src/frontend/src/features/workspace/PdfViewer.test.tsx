// TEST-AFTER coverage (ARA-037): written after PdfViewer was implemented and browser-verified, then
// mutation-verified (each case fails when the behaviour it names is removed). react-pdf is replaced by a canvas-free
// stand-in that renders a pdf.js-shaped text layer: one span[role=presentation] per line, a <br> at each line end
// and .endOfContent once the layer is complete.
import { render, screen, waitFor } from '@testing-library/react'
import type { Citation } from '@/api/types'
import PdfViewer, { type PdfViewerProps } from './PdfViewer'

const fixture = vi.hoisted(() => ({ pages: {} as Record<number, string[]>, failing: new Set<number>() }))

vi.mock('react-pdf', async () => {
  const { useEffect } = await import('react')
  type DocumentStubProps = { children?: React.ReactNode; className?: string; onLoadSuccess?: (pdf: unknown) => void }
  type PageStubProps = { pageNumber: number; onRenderTextLayerSuccess?: () => void; onRenderTextLayerError?: (error: Error) => void }
  return {
    pdfjs: { GlobalWorkerOptions: {} },
    Document: function DocumentStub({ children, className, onLoadSuccess }: DocumentStubProps) {
      useEffect(() => { onLoadSuccess?.({ numPages: 3, getPage: async () => ({ getViewport: () => ({ width: 612, height: 792 }) }) }) }, [onLoadSuccess])
      return <div className={className}>{children}</div>
    },
    Page: function PageStub({ pageNumber, onRenderTextLayerSuccess, onRenderTextLayerError }: PageStubProps) {
      useEffect(() => {
        if (fixture.failing.has(pageNumber)) onRenderTextLayerError?.(new Error('Text layer failed'))
        else onRenderTextLayerSuccess?.()
      }, [pageNumber, onRenderTextLayerSuccess, onRenderTextLayerError])
      return (
        <div className="textLayer">
          {(fixture.pages[pageNumber] ?? []).flatMap((line, index) => [<span key={`line-${index}`} role="presentation">{line}</span>, <br key={`end-${index}`} role="presentation" />])}
          <div className="endOfContent" />
        </div>
      )
    },
  }
})

/** jsdom has no layout; report a panel width so the viewer lays out its pages. */
class WidthObserver {
  private readonly callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) { this.callback = callback }
  observe() { queueMicrotask(() => this.callback([{ contentRect: { width: 800 } } as ResizeObserverEntry], this as unknown as ResizeObserver)) }
  unobserve() {}
  disconnect() {}
}

const methodLines = ['Methodology', 'The method first extracts page text, then retrieves relevant', 'chunks and generates answers grounded in those passages.', 'Datasets', 'The experiment uses the Orion-12 dataset.']
const cite = (page: number, excerpt: string): Citation => ({ chunk_id: `chunk-${page}`, document_id: 'doc-1', page, excerpt })
const onMethod = cite(2, 'The method first extracts page text, then retrieves relevant\nchunks and generates answers grounded in those passages.')

function renderViewer(highlight: PdfViewerProps['highlight']) {
  const handlers = { onDocumentLoad: vi.fn(), onPageChange: vi.fn(), onHighlight: vi.fn() }
  const element = (next: PdfViewerProps['highlight']) => <PdfViewer documentId="doc-1" zoom={1} navigation={null} highlight={next} {...handlers} />
  const view = render(element(highlight))
  return { ...handlers, view, rehighlight: (next: PdfViewerProps['highlight']) => view.rerender(element(next)) }
}
const marked = (page: number) => Array.from(screen.getByRole('group', { name: `Page ${page}` }).querySelectorAll('[data-citation-highlight]')).map((span) => span.textContent)

// The shared setup defines ResizeObserver as writable but not configurable, so it is swapped by assignment.
const SetupResizeObserver = window.ResizeObserver
beforeEach(() => {
  window.ResizeObserver = WidthObserver as unknown as typeof ResizeObserver
  fixture.pages = { 1: ['Traceable Research Systems', 'Abstract'], 2: methodLines, 3: ['Limitations', 'Twelve examples do not establish performance.'] }
  fixture.failing = new Set()
})
afterEach(() => { window.ResizeObserver = SetupResizeObserver })

describe('PdfViewer evidence jump (test-after, mutation-verified)', () => {
  test('Given a loaded PDF, Then its page count is reported and each page is a labelled group', async () => {
    const { onDocumentLoad } = renderViewer(null)
    await waitFor(() => expect(onDocumentLoad).toHaveBeenCalledWith(3))
    expect(await screen.findByRole('group', { name: 'Page 3' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'PDF document' })).toBeInTheDocument()
  })

  test('Given a citation on page 2, When its text layer renders, Then only the cited lines are marked and the jump reports "highlighted"', async () => {
    const { onHighlight } = renderViewer({ citation: onMethod, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(marked(2)).toEqual([methodLines[1], methodLines[2]])
    expect(screen.getByText(methodLines[1]!)).toHaveAttribute('data-citation-highlight', 'pulse')
    expect(onHighlight).toHaveBeenCalledTimes(1)
  })

  test('Given an excerpt that is not on the cited page, Then nothing is marked and the jump reports "page-only"', async () => {
    const { onHighlight } = renderViewer({ citation: cite(2, 'The measured answer accuracy in this synthetic experiment is 86 percent of all cases.'), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('page-only'))
    expect(marked(2)).toEqual([])
  })

  test('Given the same citation again with a new nonce, Then the passage is marked and reported again', async () => {
    const { onHighlight, rehighlight } = renderViewer({ citation: onMethod, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(1))
    rehighlight({ citation: onMethod, nonce: 2 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(2))
    expect(onHighlight).toHaveBeenLastCalledWith('highlighted')
    expect(screen.getByText(methodLines[1]!)).toHaveAttribute('data-citation-highlight', 'pulse')
  })

  test('Given the cited page cannot render its text layer, Then the jump reports "page-only"', async () => {
    fixture.failing.add(2)
    const { onHighlight } = renderViewer({ citation: onMethod, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('page-only'))
  })

  test('Given a citation beyond the first pages, Then its page is rendered before it scrolls into view', async () => {
    const { onHighlight } = renderViewer({ citation: cite(3, 'Limitations\nTwelve examples do not establish performance.'), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(marked(3)).toEqual(['Limitations', 'Twelve examples do not establish performance.'])
  })

  test('Given focus was left on the page body, When the jump lands, Then the PDF document takes focus', async () => {
    const { onHighlight } = renderViewer({ citation: onMethod, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalled())
    expect(screen.getByRole('region', { name: 'PDF document' })).toHaveFocus()
  })
})
