import { useLayoutEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { ThemeContext, type ThemeChoice, type ThemeContextValue } from './theme-context'

const STORAGE_KEY = 'theme' // index.html reads the same key before first paint
const darkQuery = '(prefers-color-scheme: dark)'

function readStoredTheme(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}
function subscribe(onChange: () => void) {
  const media = window.matchMedia(darkQuery)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}

/** Light, dark or system theme as a class on <html>, persisted per browser. Client-only: no inline scripts. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readStoredTheme)
  const systemDark = useSyncExternalStore(subscribe, () => window.matchMedia(darkQuery).matches, () => false)
  const resolvedTheme = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme
  useLayoutEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', resolvedTheme === 'dark')
    root.style.colorScheme = resolvedTheme
  }, [resolvedTheme])
  const value = useMemo<ThemeContextValue>(() => ({
    theme,
    resolvedTheme,
    setTheme: (next) => {
      const choice: ThemeChoice = next === 'light' || next === 'dark' ? next : 'system'
      try { window.localStorage.setItem(STORAGE_KEY, choice) } catch { /* private mode: the choice lasts for this visit */ }
      setThemeState(choice)
    },
  }), [theme, resolvedTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
