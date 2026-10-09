import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'
import { FetchBackedXhr } from './fake-xhr'

// Whole-app tests load lazy routes (Markdown, KaTeX, pdf.js) on first use; under a parallel run that can exceed 1s.
configure({ asyncUtilTimeout: 3000 })

afterEach(() => { cleanup(); window.localStorage.clear(); document.documentElement.className = '' })

// jsdom lacks these browser APIs that Radix, the theme provider, the sidebar and the PDF reader rely on.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false }),
  })
}
class NoopObserver { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }
if (!('ResizeObserver' in window)) Object.defineProperty(window, 'ResizeObserver', { writable: true, value: NoopObserver })
if (!('IntersectionObserver' in window)) Object.defineProperty(window, 'IntersectionObserver', { writable: true, value: NoopObserver })
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = function scrollIntoView() {}
if (!Element.prototype.scrollTo) Element.prototype.scrollTo = function scrollTo() {}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.setPointerCapture = () => {}
  Element.prototype.releasePointerCapture = () => {}
}

// Uploads report real progress through XMLHttpRequest; in tests it goes through the stubbed fetch (ARA-086).
// Assigned directly, not with vi.stubGlobal, so a test's vi.unstubAllGlobals() keeps it.
Object.defineProperty(window, 'XMLHttpRequest', { writable: true, value: FetchBackedXhr })
