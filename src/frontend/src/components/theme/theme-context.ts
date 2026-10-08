import { createContext, useContext } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'
export type ThemeContextValue = { theme: ThemeChoice; resolvedTheme: 'light' | 'dark'; setTheme: (theme: string) => void }

export const ThemeContext = createContext<ThemeContextValue | null>(null)

/** Same shape as next-themes' useTheme, so shadcn components (sonner) work unchanged. */
export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within ThemeProvider.')
  return context
}
