// TEST-AFTER coverage (ARA-037): written after PdfViewer was implemented and browser-verified, then
// mutation-verified (each case fails when the behaviour it names is removed). react-pdf is replaced by a canvas-free
// stand-in that renders a pdf.js-shaped text layer: one span[role=presentation] per line, a <br> at each line end
// and .endOfContent once the layer is complete.
import { render, screen, waitFor } from '@testing-library/react'
import type { Citation } from '@/api/types'
import PdfViewer, { type PdfViewerProps } from './PdfViewer'

const fixture = vi.hoisted(() => ({ pages: {} as Record<number, React.ReactNode[]>, failing: new Set<number>() }))

vi.mock('react-pdf', async () => {
  const { useEffect } = await import('react')
  type DocumentStubProps = { children?: React.ReactNode; className?: string; onLoadSuccess?: (pdf: unknown) => void }
  type PageStubProps = { pageNumber: number; onRenderTextLayerSuccess?: () => void; onRenderTextLayerError?: (error: Error) => void }
  return {
    pdfjs: { GlobalWorkerOptions: {} },
    Document: function DocumentStub({ children, className, onLoadSuccess }: DocumentStubProps) {
      useEffect(() => { onLoadSuccess?.({ numPages: 3, getPage: async () => ({ view: [0, 0, 612, 792], getViewport: () => ({ width: 612, height: 792, convertToViewportPoint: (x: number, y: number) => [x, 792 - y] }) }) }) }, [onLoadSuccess])
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
const unmatched = 'The measured answer accuracy in this synthetic experiment is 86 percent of all cases.'
const withBoxes = (citation: Citation, bboxes: number[][], page_end?: number): Citation => ({ ...citation, bboxes, page_end })
const onMethod = cite(2, 'The method first extracts page text, then retrieves relevant\nchunks and generates answers grounded in those passages.')

function renderViewer(highlight: PdfViewerProps['highlight']) {
  const handlers = { onDocumentLoad: vi.fn(), onPageChange: vi.fn(), onHighlight: vi.fn() }
  const element = (next: PdfViewerProps['highlight']) => <PdfViewer documentId="doc-1" zoom={1} navigation={null} highlight={next} {...handlers} />
  const view = render(element(highlight))
  return { ...handlers, view, rehighlight: (next: PdfViewerProps['highlight']) => view.rerender(element(next)) }
}
const marked = (page: number, kind = '') => Array.from(screen.getByRole('group', { name: `Page ${page}` }).querySelectorAll(kind ? `[data-citation-highlight="${kind}"]` : '[data-citation-highlight]')).map((span) => span.textContent)

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
    expect(screen.getByText(methodLines[1]!)).toHaveAttribute('data-citation-highlight', 'strong')
    expect(screen.getByText(methodLines[1]!)).toHaveAttribute('data-citation-pulse')
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
    expect(screen.getByText(methodLines[1]!)).toHaveAttribute('data-citation-pulse')
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

describe('PdfViewer passage-level evidence (test-first)', () => {
  // A whole stored chunk is cited; the claim the chip stands after is supported by its last sentence only.
  const prose = ['The method first extracts page text, then retrieves relevant', 'chunks. It generates answers grounded in those passages. The', 'experiment uses the Orion-12 dataset with twelve examples.']
  const chunk = cite(2, prose.join('\n'))
  const claim = 'The study evaluates on the Orion-12 dataset.'
  beforeEach(() => { fixture.pages[2] = prose })
  afterEach(() => vi.restoreAllMocks())

  const line = (index: number) => screen.getByRole('group', { name: 'Page 2' }).querySelectorAll<HTMLElement>('span[role="presentation"]')[index]!

  test('Given a supporting sentence that begins mid-line, When the passage is marked, Then a mark inside that line starts at the sentence', async () => {
    const { onHighlight } = renderViewer({ citation: chunk, claim, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(marked(2, 'strong')).toEqual(['The', prose[2]])
    const mark = line(1).querySelector('mark')
    expect(mark).toHaveAttribute('data-citation-highlight', 'strong')
    expect(mark).toHaveAttribute('data-citation-pulse')
    expect(line(1)).not.toHaveAttribute('data-citation-highlight')
    expect(line(1)).toHaveTextContent(prose[1]!)
    expect(marked(2, 'context')).toEqual([prose[0]])
    expect(line(0)).not.toHaveAttribute('data-citation-pulse')
  })

  // Added after a mutation check showed nothing failed when a mark ran on to the end of its line.
  test('Given a supporting sentence that starts and ends inside one line, Then the mark covers just that sentence', async () => {
    const middle = ['The method first extracts page text, then retrieves relevant', 'chunks. The experiment uses the Orion-12 dataset. Results follow', 'in the next section with twelve examples per task.']
    fixture.pages[2] = middle
    const { onHighlight } = renderViewer({ citation: cite(2, middle.join('\n')), claim, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(marked(2, 'strong')).toEqual(['The experiment uses the Orion-12 dataset.'])
    expect(line(1)).toHaveTextContent(middle[1]!)
  })

  test('Given repeated jumps, Then each line keeps its text and holds at most one mark, and a whole-excerpt jump unwraps it', async () => {
    const { onHighlight, rehighlight } = renderViewer({ citation: chunk, claim, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(1))
    rehighlight({ citation: chunk, claim, nonce: 2 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(2))
    expect(line(1).querySelectorAll('mark')).toHaveLength(1)
    expect(line(1)).toHaveTextContent(prose[1]!)
    rehighlight({ citation: chunk, nonce: 3 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(3))
    expect(line(1).querySelector('mark')).toBeNull()
    expect(line(1).childNodes).toHaveLength(1)
    expect(line(1)).toHaveAttribute('data-citation-highlight', 'strong')
  })

  test('Given a line that is not a single run of text, When only part of it is cited, Then the whole line is marked instead', async () => {
    fixture.pages[2] = [prose[0], <>chunks. It generates answers grounded in those passages. <i>The</i></>, prose[2]]
    const { onHighlight } = renderViewer({ citation: chunk, claim, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(line(1).querySelector('mark')).toBeNull()
    expect(line(1)).toHaveAttribute('data-citation-highlight', 'strong')
    expect(marked(2, 'strong')).toEqual([prose[1], prose[2]])
  })

  test('Given no claim, Then the whole excerpt is strong and nothing is context', async () => {
    const { onHighlight } = renderViewer({ citation: chunk, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(marked(2, 'strong')).toEqual(prose)
    expect(marked(2, 'context')).toEqual([])
  })

  test('Given the passage lands, Then the first strong line is scrolled to the vertical centre of the reader', async () => {
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(600)
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      return this.getAttribute('data-citation-highlight') === 'strong' ? new DOMRect(0, 1000, 300, 20) : new DOMRect(0, 0, 0, 0)
    })
    const scrollTo = vi.spyOn(Element.prototype, 'scrollTo')
    const { onHighlight } = renderViewer({ citation: chunk, claim, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    // The line's centre (1000 + 20 / 2) sits half the reader's height (600 / 2) below the top of the view.
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 710, behavior: 'smooth' })
  })
})

describe('PdfViewer region fallback (ARA-089, test-first)', () => {
  afterEach(() => vi.restoreAllMocks())
  // PyMuPDF boxes: [page, x0, y0, x1, y1] in points, top-left origin; the stub page is 612 x 792.
  const box = [2, 61.2, 79.2, 306, 158.4]
  const regions = (page: number) => Array.from(screen.getByRole('group', { name: `Page ${page}` }).querySelectorAll<HTMLElement>('[data-citation-region]'))

  test('Given text that cannot be found but stored boxes, Then the boxes are outlined on their page and the jump reports "region"', async () => {
    const { onHighlight } = renderViewer({ citation: withBoxes(cite(2, unmatched), [box]), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('region'))
    expect(onHighlight).toHaveBeenCalledTimes(1)
    const [outline] = regions(2)
    expect(outline).toBeDefined()
    expect(outline!.style.left).toBe('10%')
    expect(outline!.style.top).toBe('10%')
    expect(outline!.style.width).toBe('40%')
    expect(outline!.style.height).toBe('10%')
    expect(outline).toHaveAttribute('data-citation-pulse')
    expect(outline).toHaveAttribute('aria-hidden', 'true')
    expect(marked(2)).toEqual([])
  })

  test('Given text that is found, Then the text is marked and the boxes are not drawn', async () => {
    const { onHighlight } = renderViewer({ citation: withBoxes(onMethod, [box]), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('highlighted'))
    expect(regions(2)).toHaveLength(0)
  })

  test('Given neither text nor boxes, Then nothing is drawn and the jump reports "page-only"', async () => {
    const { onHighlight } = renderViewer({ citation: withBoxes(cite(2, unmatched), []), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('page-only'))
    expect(regions(2)).toHaveLength(0)
  })

  test('Given boxes that do not fit any page, Then the jump reports "page-only"', async () => {
    const { onHighlight } = renderViewer({ citation: withBoxes(cite(2, unmatched), [[2, 5, 5]]), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('page-only'))
  })

  test('Given the text layer fails, Then stored boxes still give a region', async () => {
    fixture.failing.add(2)
    const { onHighlight } = renderViewer({ citation: withBoxes(onMethod, [box]), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('region'))
    expect(regions(2)).toHaveLength(1)
  })

  test('Given a citation across two pages, Then each page gets the boxes that carry its number', async () => {
    const { onHighlight } = renderViewer({ citation: withBoxes(cite(2, unmatched), [box, [2, 0, 700, 612, 790], [3, 0, 0, 612, 100]], 3), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('region'))
    expect(regions(2)).toHaveLength(2)
    expect(regions(3)).toHaveLength(1)
  })

  test('Given a second citation, Then the earlier outline and marks are cleared', async () => {
    const { onHighlight, rehighlight } = renderViewer({ citation: withBoxes(cite(2, unmatched), [box]), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(1))
    rehighlight({ citation: cite(3, 'Limitations\nTwelve examples do not establish performance.'), nonce: 2 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(2))
    expect(regions(2)).toHaveLength(0)
    expect(marked(3)).toEqual(['Limitations', 'Twelve examples do not establish performance.'])
    rehighlight({ citation: withBoxes(cite(1, unmatched), [[1, 0, 0, 100, 100]]), nonce: 3 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(3))
    expect(marked(3)).toEqual([])
    expect(regions(1)).toHaveLength(1)
  })

  test('Given the same citation again, Then the outline is redrawn so it pulses again', async () => {
    const citation = withBoxes(cite(2, unmatched), [box])
    const { onHighlight, rehighlight } = renderViewer({ citation, nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(1))
    const first = regions(2)[0]
    rehighlight({ citation, nonce: 2 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledTimes(2))
    expect(regions(2)).toHaveLength(1)
    expect(regions(2)[0]).not.toBe(first)
  })

  test('Given the zoom changes, Then the outline stays on the page at the same percentages', async () => {
    const citation = withBoxes(cite(2, unmatched), [box])
    const handlers = { onDocumentLoad: vi.fn(), onPageChange: vi.fn(), onHighlight: vi.fn() }
    const highlight = { citation, nonce: 1 }
    const element = (zoom: number) => <PdfViewer documentId="doc-1" zoom={zoom} navigation={null} highlight={highlight} {...handlers} />
    const view = render(element(1))
    await waitFor(() => expect(handlers.onHighlight).toHaveBeenCalledWith('region'))
    view.rerender(element(2))
    expect(regions(2)).toHaveLength(1)
    expect(regions(2)[0]!.style.left).toBe('10%')
    expect(handlers.onHighlight).toHaveBeenCalledTimes(1)
  })

  test('Given the region lands, Then its vertical centre is scrolled to the centre of the reader', async () => {
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(600)
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      return this.hasAttribute('data-citation-region') ? new DOMRect(0, 1000, 300, 80) : new DOMRect(0, 0, 0, 0)
    })
    const scrollTo = vi.spyOn(Element.prototype, 'scrollTo')
    const { onHighlight } = renderViewer({ citation: withBoxes(cite(2, unmatched), [box]), nonce: 1 })
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith('region'))
    // centre 1000 + 80 / 2, less half the reader's height
    await waitFor(() => expect(scrollTo).toHaveBeenLastCalledWith({ top: 740, behavior: 'smooth' }))
  })
})
