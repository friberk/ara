import type { Citation } from '@/api/types'

/**
 * What the reader keeps of each page to place a stored box: pdf.js's own scale-1 viewport (which carries the page's
 * rotation and CropBox offset) and the page's `view` (the visible CropBox in PDF user space).
 */
export type PageGeometry = {
  view: readonly number[]
  viewport: { width: number; height: number; convertToViewportPoint: (x: number, y: number) => number[] }
}

/** A box as percentages of the rendered page, so it stays aligned at any zoom without being measured again. */
export type Region = { page: number; left: number; top: number; width: number; height: number }

const clamp = (value: number) => Math.min(100, Math.max(0, value))

/**
 * Converts a citation's stored boxes ([page, x0, y0, x1, y1] from PyMuPDF) to regions on the rendered pages.
 *
 * PyMuPDF reports points with a top-left origin, y down, relative to the page's CropBox, and does not turn them with
 * a rotated page. So a point is first placed in PDF user space (CropBox left + x, CropBox top - y) and then passed
 * through the pdf.js viewport, which applies rotation and offset. Checked against real cropped and rotated PDFs.
 * Boxes that are malformed, empty or on a page without geometry are dropped.
 */
export function regionsFor(citation: Pick<Citation, 'bboxes' | 'page' | 'page_end'>, pages: ReadonlyMap<number, PageGeometry>): Region[] {
  const regions: Region[] = []
  for (const box of citation.bboxes ?? []) {
    const [page, x0, y0, x1, y1] = box
    const geometry = page === undefined ? undefined : pages.get(page)
    if (page === undefined || !geometry || box.length < 5 || !box.every(Number.isFinite)) continue
    const [left = 0, , , top = 0] = geometry.view
    const { viewport } = geometry
    const [ax = 0, ay = 0] = viewport.convertToViewportPoint(left + x0!, top - y0!)
    const [bx = 0, by = 0] = viewport.convertToViewportPoint(left + x1!, top - y1!)
    const l = clamp((Math.min(ax, bx) / viewport.width) * 100)
    const t = clamp((Math.min(ay, by) / viewport.height) * 100)
    const r = clamp((Math.max(ax, bx) / viewport.width) * 100)
    const b = clamp((Math.max(ay, by) / viewport.height) * 100)
    if (r - l <= 0 || b - t <= 0) continue
    regions.push({ page, left: l, top: t, width: r - l, height: b - t })
  }
  return regions
}
