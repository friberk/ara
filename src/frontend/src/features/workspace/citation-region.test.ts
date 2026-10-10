// ARA-089. PyMuPDF block boxes are [page, x0, y0, x1, y1] in points, origin top-left, y down, relative to the
// page's CropBox and NOT rotated with the page. The expectations below were taken from real PDFs: PyMuPDF boxes and
// pdf.js text positions were compared for plain, cropped and rotated pages.
import type { Citation } from '@/api/types'
import { regionsFor, type PageGeometry } from './citation-region'

// pdfjs-dist exports PageViewport as a type only, so this is its scale-1 transform for each rotation. The four
// formulas were checked against getViewport(...).convertToViewportPoint on real PDFs (see the ARA-089 journal).
function geometry(view: number[], rotation: 0 | 90 | 180 | 270): PageGeometry {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = view
  const turned = rotation === 90 || rotation === 270
  const convert = {
    0: (x: number, y: number) => [x - x0, y1 - y],
    90: (x: number, y: number) => [y - y0, x - x0],
    180: (x: number, y: number) => [x1 - x, y - y0],
    270: (x: number, y: number) => [y1 - y, x1 - x],
  }[rotation]
  return { view, viewport: { width: turned ? y1 - y0 : x1 - x0, height: turned ? x1 - x0 : y1 - y0, convertToViewportPoint: convert } }
}
const cite = (bboxes: number[][], page = 1, page_end?: number): Pick<Citation, 'bboxes' | 'page' | 'page_end'> => ({ bboxes, page, page_end })
const near = (actual: number | undefined, expected: number) => expect(actual).toBeCloseTo(expected, 1)

describe('regionsFor (box to percentage of the rendered page)', () => {
  test('Given an upright Letter page, Then a box becomes percentages of the page', () => {
    const pages = new Map([[1, geometry([0, 0, 612, 792], 0)]])
    const [region] = regionsFor(cite([[1, 61.2, 79.2, 306, 158.4]]), pages)
    expect(region?.page).toBe(1)
    near(region?.left, 10); near(region?.top, 10); near(region?.width, 40); near(region?.height, 10)
  })

  test('Given a CropBox that does not start at the origin, Then boxes stay relative to the visible area', () => {
    // fixture from PyMuPDF: text at the cropped page's (150, 178.5)-(235.6, 206) inside a 400 x 500 CropBox
    const pages = new Map([[1, geometry([50, 192, 450, 692], 0)]])
    const [region] = regionsFor(cite([[1, 150, 178.5, 235.6, 206]]), pages)
    near(region?.left, 37.5); near(region?.top, 35.7); near(region?.width, 21.4); near(region?.height, 5.5)
  })

  test('Given a page rotated 90 degrees, Then the unrotated box is turned with the page', () => {
    // pdf.js drew that text at x 294-321.5, y 150-235.6 of the 500 x 400 viewport
    const pages = new Map([[1, geometry([50, 192, 450, 692], 90)]])
    const [region] = regionsFor(cite([[1, 150, 178.5, 235.6, 206]]), pages)
    near(region?.left, (294 / 500) * 100); near(region?.top, (150 / 400) * 100)
    near(region?.width, (27.5 / 500) * 100); near(region?.height, (85.6 / 400) * 100)
  })

  test('Given a page rotated 270 degrees, Then the unrotated box is turned with the page', () => {
    const pages = new Map([[1, geometry([50, 192, 450, 692], 270)]])
    const [region] = regionsFor(cite([[1, 150, 178.5, 235.6, 206]]), pages)
    near(region?.left, (178.5 / 500) * 100); near(region?.top, (164.4 / 400) * 100)
    near(region?.width, (27.5 / 500) * 100); near(region?.height, (85.6 / 400) * 100)
  })

  test('Given boxes on two pages, Then each region carries its own page and unknown pages are skipped', () => {
    const pages = new Map([[1, geometry([0, 0, 612, 792], 0)], [2, geometry([0, 0, 612, 792], 0)]])
    const regions = regionsFor(cite([[1, 0, 0, 100, 100], [2, 0, 0, 100, 100], [9, 0, 0, 100, 100]], 1, 2), pages)
    expect(regions.map((region) => region.page)).toEqual([1, 2])
  })

  test('Given malformed, empty or outlying boxes, Then they are dropped or clamped to the page', () => {
    const pages = new Map([[1, geometry([0, 0, 612, 792], 0)]])
    expect(regionsFor(cite([[1, 10, 10], [1, Number.NaN, 0, 5, 5], [1, 50, 50, 50, 90]]), pages)).toEqual([])
    const [region] = regionsFor(cite([[1, -20, 700, 700, 900]]), pages)
    expect(region).toMatchObject({ left: 0, width: 100 })
    near(region?.top, (700 / 792) * 100); near((region?.top ?? 0) + (region?.height ?? 0), 100)
  })

  test('Given a citation without boxes or geometry, Then there are no regions', () => {
    expect(regionsFor(cite([]), new Map())).toEqual([])
    expect(regionsFor({ page: 1 }, new Map([[1, geometry([0, 0, 612, 792], 0)]]))).toEqual([])
  })
})
