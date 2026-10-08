import { createContext, useContext } from 'react'
import { createPortal } from 'react-dom'

export const HeaderSlotContext = createContext<HTMLElement | null>(null)

/** Renders page-specific controls (a title, a chat switcher) into the shell's top bar. */
export function ShellHeader({ children }: { children: React.ReactNode }) {
  const slot = useContext(HeaderSlotContext)
  return slot ? createPortal(children, slot) : null
}
