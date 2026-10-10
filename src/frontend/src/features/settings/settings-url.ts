import type { MouseEvent } from 'react'
import { useLocation, useNavigate, type To } from 'react-router-dom'

/** Settings opens over the current page; `?settings=<category>` names the open category so it can be linked. */
export const SETTINGS_PARAM = 'settings'
export const settingsCategories = ['general', 'models', 'library', 'open-models'] as const
export type SettingsCategory = (typeof settingsCategories)[number]

// History entries this app pushed when it opened Settings; closing one goes back instead of adding another.
type OpenedState = { settingsOpened?: boolean }

// The control that opened Settings gets focus back when it closes. Only one Settings dialog exists at a time.
let opener: HTMLElement | null = null
export function settingsOpener() { return opener?.isConnected ? opener : null }

function rememberOpener() { opener = document.activeElement instanceof HTMLElement ? document.activeElement : null }

/**
 * Open, link to, switch and close the Settings dialog through the URL. Opening pushes one history entry, so the
 * browser's Back button closes it; switching category replaces that entry.
 */
export function useSettingsDialog() {
  const location = useLocation()
  const navigate = useNavigate()
  const value = new URLSearchParams(location.search).get(SETTINGS_PARAM)
  const isOpen = value !== null
  const opened = (location.state as OpenedState | null)?.settingsOpened === true

  const to = (category: SettingsCategory | '' = '', hash = ''): To => {
    const search = new URLSearchParams(location.search)
    search.set(SETTINGS_PARAM, category)
    return { pathname: location.pathname, search: `?${search}`, hash }
  }
  const state = isOpen ? location.state : { settingsOpened: true } satisfies OpenedState
  const open = (category: SettingsCategory | '' = '', hash = '') => {
    if (!isOpen) rememberOpener()
    navigate(to(category, hash), { replace: isOpen, state })
  }
  const close = () => {
    if (opened) { navigate(-1); return }
    const search = new URLSearchParams(location.search)
    search.delete(SETTINGS_PARAM)
    navigate({ pathname: location.pathname, search: search.size ? `?${search}` : '' }, { replace: true })
  }
  /** Props for a <Link> that opens Settings on a category, from inside the dialog or from any page. */
  const link = (category: SettingsCategory, hash = '') => ({
    to: to(category, hash),
    state,
    replace: isOpen,
    onClick: (event: MouseEvent) => { if (!isOpen && !event.defaultPrevented) rememberOpener() },
  })
  return { isOpen, value, open, close, link }
}
