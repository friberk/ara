import { act, renderHook } from '@testing-library/react'
import { ThemeProvider } from './ThemeProvider'
import { useTheme } from './theme-context'

const original = window.matchMedia
let listeners: Array<() => void> = []
function stubSystem(isDark: () => boolean) {
  window.matchMedia = ((query: string) => ({ get matches() { return query.includes('dark') && isDark() }, media: query, onchange: null, addEventListener: (_: string, listener: () => void) => { listeners.push(listener) }, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia
}
afterEach(() => { window.matchMedia = original; listeners = [] })
const mount = () => renderHook(() => useTheme(), { wrapper: ThemeProvider })

test('Given no saved choice and a dark system, Then the system theme applies dark tokens', () => {
  stubSystem(() => true)
  const { result } = mount()
  expect(result.current).toMatchObject({ theme: 'system', resolvedTheme: 'dark' })
  expect(document.documentElement).toHaveClass('dark')
  expect(document.documentElement.style.colorScheme).toBe('dark')
})

test('Given a saved light choice, Then it wins over a dark system and choosing System follows the system again', () => {
  stubSystem(() => true)
  window.localStorage.setItem('theme', 'light')
  const { result } = mount()
  expect(result.current).toMatchObject({ theme: 'light', resolvedTheme: 'light' })
  expect(document.documentElement).not.toHaveClass('dark')
  act(() => result.current.setTheme('system'))
  expect(window.localStorage.getItem('theme')).toBe('system')
  expect(document.documentElement).toHaveClass('dark')
})

test('Given the system theme changes, When following the system, Then the page follows it', () => {
  let dark = false
  stubSystem(() => dark)
  const { result } = mount()
  expect(result.current.resolvedTheme).toBe('light')
  dark = true
  act(() => listeners.forEach((listener) => listener()))
  expect(result.current.resolvedTheme).toBe('dark')
})

test('Given an unknown stored value, Then the theme falls back to System', () => {
  stubSystem(() => false)
  window.localStorage.setItem('theme', 'sepia')
  expect(mount().result.current).toMatchObject({ theme: 'system', resolvedTheme: 'light' })
})
