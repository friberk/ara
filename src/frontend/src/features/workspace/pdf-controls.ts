import { useCallback, useState } from 'react'

/** Zoom is relative to the reader's width: 1 fits the page to the panel. */
export const ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3]
/** A request to bring a page into view; the nonce repeats a jump to the same page. */
export type PdfNavigation = { documentId: string; page: number; nonce: number }

/**
 * Toolbar state shared by the reader toolbar and the viewer. Page count and position belong to the document they
 * were reported for, so switching to an earlier PDF version starts from its own first page.
 */
export function usePdfControls(documentId: string | null) {
  const [zoom, setZoom] = useState(1)
  const [loaded, setLoaded] = useState<{ documentId: string; numPages: number } | null>(null)
  const [current, setCurrent] = useState<{ documentId: string; page: number } | null>(null)
  const [navigation, setNavigation] = useState<PdfNavigation | null>(null)
  const numPages = loaded && loaded.documentId === documentId ? loaded.numPages : null
  const page = current && current.documentId === documentId ? current.page : 1

  const onDocumentLoad = useCallback((count: number) => { if (documentId) setLoaded({ documentId, numPages: count }) }, [documentId])
  const onPageChange = useCallback((next: number) => { if (documentId) setCurrent({ documentId, page: next }) }, [documentId])
  const goTo = useCallback((target: number) => {
    if (!documentId || !numPages) return
    const clamped = Math.min(Math.max(1, Math.round(target)), numPages)
    setCurrent({ documentId, page: clamped })
    setNavigation((previous) => ({ documentId, page: clamped, nonce: (previous?.nonce ?? 0) + 1 }))
  }, [documentId, numPages])

  return {
    zoom,
    numPages,
    page,
    navigation: navigation && navigation.documentId === documentId ? navigation : null,
    canZoomIn: zoom < ZOOM_STEPS[ZOOM_STEPS.length - 1]!,
    canZoomOut: zoom > ZOOM_STEPS[0]!,
    zoomIn: () => setZoom((value) => ZOOM_STEPS.find((step) => step > value) ?? value),
    zoomOut: () => setZoom((value) => ZOOM_STEPS.filter((step) => step < value).at(-1) ?? value),
    fitWidth: () => setZoom(1),
    goTo,
    onDocumentLoad,
    onPageChange,
  }
}

export type PdfControls = ReturnType<typeof usePdfControls>
