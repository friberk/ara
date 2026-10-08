import { useContext } from 'react'
import { createPortal } from 'react-dom'
import { HeaderSlotContext } from './shell-header-context'


/** Renders page-specific controls (a title, a chat switcher) into the shell's top bar. */
export function ShellHeader({ children }: { children: React.ReactNode }) {
  const slot = useContext(HeaderSlotContext)
  return slot ? createPortal(children, slot) : null
}
