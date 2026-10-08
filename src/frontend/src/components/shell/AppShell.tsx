import { lazy, Suspense, useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { GenerationSettingsProvider } from '@/components/composer/generation-settings'
import { LoadingState } from '@/components/feedback/LoadingState'
import { AppSidebar } from './AppSidebar'
import { HeaderSlotContext } from './shell-header'

const CommandPalette = lazy(() => import('./CommandPalette'))

/**
 * Chat-app frame: collapsible sidebar, a slim top bar that pages fill through <ShellHeader>,
 * and one scrolling <main>. Pages that need fixed panes (the paper workspace) fill the main area instead.
 */
export function AppShell() {
  const [headerSlot, setHeaderSlot] = useState<HTMLElement | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [paletteLoaded, setPaletteLoaded] = useState(false)
  const openPalette = (open: boolean) => { if (open) setPaletteLoaded(true); setPaletteOpen(open) }
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); setPaletteLoaded(true); setPaletteOpen((open) => !open) }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
  return (
    <GenerationSettingsProvider>
      <SidebarProvider className="h-svh overflow-hidden">
        <a href="#main" className="sr-only z-50 rounded-md bg-background px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:fixed focus:top-2 focus:left-2">Skip to content</a>
        <AppSidebar onOpenSearch={() => openPalette(true)} />
        <div data-slot="sidebar-inset" className="relative flex h-svh min-w-0 flex-1 flex-col bg-background">
          <header className="flex h-12 shrink-0 items-center gap-1 px-2">
            <Tooltip>
              <TooltipTrigger asChild><SidebarTrigger className="text-muted-foreground" /></TooltipTrigger>
              <TooltipContent side="bottom">Toggle sidebar <span className="text-muted-foreground">⌘B</span></TooltipContent>
            </Tooltip>
            <div ref={setHeaderSlot} className="flex min-w-0 flex-1 items-center gap-2" />
          </header>
          <HeaderSlotContext.Provider value={headerSlot}>
            <main id="main" tabIndex={-1} className="relative flex min-h-0 flex-1 flex-col overflow-y-auto outline-none">
              <Suspense fallback={<LoadingState className="mx-auto">Loading…</LoadingState>}>
                <Outlet />
              </Suspense>
            </main>
          </HeaderSlotContext.Provider>
        </div>
        {paletteLoaded && <Suspense fallback={null}><CommandPalette open={paletteOpen} onOpenChange={openPalette} /></Suspense>}
      </SidebarProvider>
    </GenerationSettingsProvider>
  )
}
